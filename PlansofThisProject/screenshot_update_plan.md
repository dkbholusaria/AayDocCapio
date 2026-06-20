# Screenshot Update Plan

## Goal
Replace the old screenshots used in the Help Manual with the new set located at
`/home/deepak/projects/AayDocCapio/testdata/Screenshots`.
Because file names differ, we will match images by visual similarity (perceptual hash) and then:
1. Copy/replace matching old images with the new ones.
2. Add any truly new images.
3. Delete obsolete old images.
4. Ensure the Help Manual generation code points to the correct assets.

## Steps
1. **Create evaluation script** (`scripts/evaluate_screenshots.py`).
   - Scans both directories, computes `phash` for each image, finds best matches.
   - Generates `scripts/screenshot_evaluation.json` with mapping and action (`replace`, `new`).
2. **Run the script** to produce the JSON mapping.
3. **Create apply script** (`scripts/apply_screenshot_updates.py`).
   - Reads the JSON, copies/replaces files, adds new files, removes unmatched old files.
4. **Execute apply script**.
5. **Update Help‑Manual code** (`ui/dialogs.py`).
   - **Option A**: Keep hard‑coded keys – just replace files in place (no code change).
   - **Option B**: Make the mapping dynamic by loading `screenshot_evaluation.json` and building `img_uris` at runtime (≈10‑line edit).
6. **Verify** by launching the app and opening Help → User Manual.
7. **Document** the change in `Documentation/ISSUES_BACKLOG.md` and commit the new scripts and any code changes.

## Dependencies
- Python packages: `pillow`, `imagehash` (install via `.venv/bin/pip install pillow imagehash`).

## Files involved
- `scripts/evaluate_screenshots.py` (created)
- `scripts/apply_screenshot_updates.py` (to be created)
- `scripts/screenshot_evaluation.json` (generated output)
- `resources/screenshots/` (old assets)
- `testdata/Screenshots/` (new assets)
- `ui/dialogs.py` (Help‑Manual generation)

## Approval
Please confirm which option (A or B) you prefer and whether I should proceed with installing dependencies and running the scripts.
