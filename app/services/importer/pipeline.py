"""Import pipeline: orchestrates SSRF check, fetch, parse, image download,
geocoding, duplicate detection and DB persistence."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models.apartment import Apartment
from app.models.job import ImportJob, ImportJobStatus
from app.models.listing import (
    ApartmentChange,
    ApartmentImage,
    ApartmentSnapshot,
    ListingSource,
)
from app.models.location import TargetAddress
from app.services.geocoding import geocode
from app.services.image import save_image
from app.services.importer import get_importer_for
from app.services.importer.base import ImporterResult
from app.services.routing import calculate_for_apartment
from app.services.ssrf import SSRFError, safe_get, validate_import_url


logger = logging.getLogger(__name__)


WARNING_RULES = {
    # Only flag when we have absolutely nothing locating the property —
    # partial info (just a postal code, a city, or a street) is acceptable.
    "missing_address": lambda apt: not any([
        (apt.address or "").strip(),
        (apt.city or "").strip(),
        (apt.postal_code or "").strip(),
    ]),
    "no_photos": lambda apt: not apt.images,
    "few_photos": lambda apt: 0 < len(apt.images) < 3,
    "high_deposit": lambda apt: (
        apt.deposit and apt.price and float(apt.deposit) > 4 * float(apt.price)
    ),
    "limited_lease": lambda apt: bool(apt.lease_duration_limited),
    # Geocoding failure only matters when we have a meaningful street-level address.
    "geocoding_failed": lambda apt: bool((apt.address or "").strip())
        and bool((apt.city or apt.postal_code or "").strip())
        and (apt.lat is None or apt.lng is None),
}


def compute_warning_flags(apt: Apartment) -> list[str]:
    flags = []
    for name, rule in WARNING_RULES.items():
        try:
            if rule(apt):
                flags.append(name)
        except Exception:
            continue
    if apt.commission and float(apt.commission) > 0:
        flags.append("commission")
    return flags


def _save_snapshot(apt_id: int, source_id: int | None, html: str, text: str | None) -> None:
    snap = ApartmentSnapshot(
        apartment_id=apt_id,
        listing_source_id=source_id,
        text_content=(text or "")[:200_000],
    )
    snap_dir = Path(current_app.config["SNAPSHOT_DIR"]) / str(apt_id)
    try:
        snap_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        html_path = snap_dir / f"{ts}.html"
        html_path.write_text(html or "", encoding="utf-8", errors="replace")
        snap.html_path = str(html_path.relative_to(Path(current_app.config["SNAPSHOT_DIR"])))
    except Exception:
        logger.exception("Could not write HTML snapshot for apartment %s", apt_id)
    db.session.add(snap)


# Generous minimums: only filter out things that clearly aren't gallery photos
# (icons, sponsor badges, tracking pixels). Real listing photos — even compressed
# JPEGs — are well above these thresholds.
MIN_IMAGE_WIDTH = 320
MIN_IMAGE_HEIGHT = 220
MIN_IMAGE_BYTES = 4 * 1024  # 4 KB
# Hamming distance below this counts as "near-duplicate"; raise it slightly
# so that resized variants of the same photo collapse together but distinct
# rooms (which often share lighting/walls) don't.
PHASH_MIN_DISTANCE = 2


def _phash_close(new_hash: str | None, existing: list[str]) -> bool:
    if not new_hash:
        return False
    try:
        import imagehash
    except ImportError:
        return False
    try:
        new = imagehash.hex_to_hash(new_hash)
    except Exception:
        return False
    for h in existing:
        if not h:
            continue
        try:
            if abs(new - imagehash.hex_to_hash(h)) <= PHASH_MIN_DISTANCE:
                return True
        except Exception:
            continue
    return False


def _download_images(apt_id: int, urls: list[str]) -> int:
    user_agent = current_app.config.get("NOMINATIM_USER_AGENT", "flat-finder/1.0")
    max_size = current_app.config.get("MAX_IMAGE_DOWNLOAD_SIZE_MB", 10) * 1024 * 1024
    saved = 0
    saved_hashes: list[str] = []
    for url in urls:
        try:
            resp = safe_get(url, timeout=15, max_size_bytes=max_size, user_agent=user_agent)
            if resp.status_code != 200 or not resp.content:
                continue
            if len(resp.content) < MIN_IMAGE_BYTES:
                logger.debug("Skipped %s: too small (%d bytes)", url, len(resp.content))
                continue
            meta = save_image(apt_id, url, resp.content)
        except SSRFError as e:
            logger.warning("Skipped image %s: %s", url, e)
            continue
        except Exception:
            logger.exception("Image download failed: %s", url)
            continue

        w, h = meta.get("width"), meta.get("height")
        # Reject low-quality variants / thumbnails masquerading as full photos.
        if w is not None and h is not None and (w < MIN_IMAGE_WIDTH or h < MIN_IMAGE_HEIGHT):
            logger.debug("Skipped %s: below min size (%sx%s)", url, w, h)
            continue

        # Reject near-duplicates of images we already saved this batch.
        phash = meta.get("perceptual_hash")
        if _phash_close(phash, saved_hashes):
            logger.debug("Skipped %s: near-duplicate (phash=%s)", url, phash)
            continue
        if phash:
            saved_hashes.append(phash)

        db.session.add(ApartmentImage(
            apartment_id=apt_id,
            local_path=meta["local_path"],
            thumbnail_path=meta.get("thumbnail_path"),
            original_url=url,
            width=w,
            height=h,
            file_size=meta.get("file_size"),
            perceptual_hash=phash,
        ))
        saved += 1
    return saved


def _apply_extracted_fields(apt: Apartment, fields: dict) -> dict:
    """Apply extracted fields to an Apartment, returning dict of fields actually changed."""
    changes: dict = {}
    for key, value in fields.items():
        if not hasattr(apt, key) or value is None:
            continue
        current = getattr(apt, key)
        if str(current) == str(value):
            continue
        setattr(apt, key, value)
        changes[key] = (current, value)
    return changes


def _record_changes(apt: Apartment, changes: dict, detected_by: str) -> None:
    for field, (old, new) in changes.items():
        db.session.add(ApartmentChange(
            apartment_id=apt.id,
            field_name=field,
            old_value=str(old) if old is not None else None,
            new_value=str(new) if new is not None else None,
            detected_by=detected_by,
        ))


def run_import_job(job_id: int) -> None:
    """Execute an import job. Designed to be called from RQ worker or inline."""
    from app.services.duplicate import find_duplicate_candidates

    job = db.session.get(ImportJob, job_id)
    if not job:
        logger.error("Import job %s not found", job_id)
        return

    job.status = ImportJobStatus.RUNNING
    job.started_at = datetime.utcnow()
    db.session.commit()

    try:
        url = validate_import_url(job.url)

        max_size = current_app.config.get("MAX_IMPORT_DOWNLOAD_SIZE_MB", 20) * 1024 * 1024
        timeout = current_app.config.get("IMPORT_HTTP_TIMEOUT", 15)
        user_agent = current_app.config.get("NOMINATIM_USER_AGENT", "flat-finder/1.0")

        resp = safe_get(url, timeout=timeout, max_size_bytes=max_size, user_agent=user_agent)
        if resp.status_code != 200:
            raise RuntimeError(f"Source returned HTTP {resp.status_code}")
        html = resp.text

        importer = get_importer_for(url)
        result: ImporterResult = importer.extract(url, html, resp)

        # Find existing source by canonical URL or platform+external_id
        existing_source: ListingSource | None = None
        if result.canonical_url:
            existing_source = ListingSource.query.filter_by(
                canonical_url=result.canonical_url
            ).first()
        if not existing_source and result.platform and result.external_id:
            existing_source = ListingSource.query.filter_by(
                platform=result.platform, external_id=result.external_id
            ).first()
        if not existing_source:
            existing_source = ListingSource.query.filter_by(url=url).first()

        if existing_source:
            apt = existing_source.apartment
            source = existing_source
            field_changes = _apply_extracted_fields(apt, result.fields)
            _record_changes(apt, field_changes, detected_by="refresh")
            source.date_last_refreshed = datetime.utcnow()
            source.last_http_status = resp.status_code
            source.last_error = None
            source.is_active = True
            apt.is_offline = False
            new_apartment = False
        else:
            apt = Apartment(created_by_id=job.created_by_id)
            _apply_extracted_fields(apt, result.fields)
            db.session.add(apt)
            db.session.flush()
            source = ListingSource(
                apartment_id=apt.id,
                url=url,
                canonical_url=result.canonical_url,
                platform=result.platform,
                external_id=result.external_id,
                date_first_imported=datetime.utcnow(),
                date_last_refreshed=datetime.utcnow(),
                last_http_status=resp.status_code,
            )
            db.session.add(source)
            db.session.flush()
            new_apartment = True

        # Snapshot
        _save_snapshot(apt.id, source.id, html, result.text_snapshot)

        # Geocode if needed
        if (apt.lat is None or apt.lng is None) and apt.address:
            coords = geocode(apt.address)
            if coords:
                apt.lat, apt.lng = coords

        # Download images (only for new apartments to avoid blowing up storage on refresh)
        if new_apartment:
            _download_images(apt.id, result.image_urls)

        db.session.flush()  # ensure images present for warning rules

        # Travel times
        if apt.lat is not None and apt.lng is not None:
            for tgt in TargetAddress.query.filter_by(is_active=True).all():
                if tgt.lat is None or tgt.lng is None:
                    continue
                calculate_for_apartment(apt, tgt)

        # Warning flags
        apt.warning_flags = compute_warning_flags(apt)

        # Duplicate detection (only for newly created apartments)
        if new_apartment:
            find_duplicate_candidates(apt)

        job.apartment_id = apt.id
        job.listing_source_id = source.id
        job.status = ImportJobStatus.DONE
        job.finished_at = datetime.utcnow()
        db.session.commit()
        logger.info("Import job %s finished, apartment_id=%s", job.id, apt.id)
    except Exception as e:
        db.session.rollback()
        logger.exception("Import job %s failed", job_id)
        # Reload job (rollback might have detached it)
        job = db.session.get(ImportJob, job_id)
        if job is not None:
            job.status = ImportJobStatus.FAILED
            job.error_message = str(e)[:1000]
            job.finished_at = datetime.utcnow()
            db.session.commit()


def run_refresh_for_source(source_id: int) -> None:
    """Re-fetch an existing listing source's URL via the import pipeline."""
    src = db.session.get(ListingSource, source_id)
    if not src:
        return
    job = ImportJob(
        url=src.url,
        status=ImportJobStatus.PENDING,
        listing_source_id=src.id,
        apartment_id=src.apartment_id,
    )
    db.session.add(job)
    db.session.commit()
    run_import_job(job.id)
