.PHONY: audit-package

PYTHON ?= uv run python

audit-package:
	$(PYTHON) scripts/sanitize_release_archive.py --output /tmp/memco_safe.zip
	$(PYTHON) scripts/scan_archive_for_secrets.py /tmp/memco_safe.zip
