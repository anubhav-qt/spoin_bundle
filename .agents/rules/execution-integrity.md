# Execution Integrity & Image Sourcing Rules

## 1. Absolute Directive: NEVER EVER DO WHAT IS NOT TOLD

- **Never take shortcuts:** If a step is mandated (e.g. visual inspection using vision capability), it must be performed for every single item without exception.
- **No unapproved helper scripts:** Do NOT write or execute helper scripts to scrape archive metadata, generate text, synthesize descriptions, or simulate visual inspection.
- **Mandatory Multimodal Vision Inspection:** You must download each image to `scratch/` and call `view_file` on it to inspect its actual pixels using your vision capability before writing any description.
- **Zero Hallucination:** Never fabricate CDN URLs, file hashes, or asset paths. All URLs must return verified `HTTP 200 OK`.
- **Honesty over Volume:** It is completely unacceptable to pretend to have visually inspected an image when metadata was used instead. Do each image genuinely.

## 2. Image Manifest Contract (§ 10 & ADR-0095)
- Describe strictly what is visible in the frame: composition, palette, morphological structures, lighting, perspective, and surface details.
- Never use archive captions, alt text, or filenames as descriptions.
- Approved licenses only: `cc0`, `public-domain`, `cc-by`, `cc-by-sa`, `unsplash`, `pexels`, `pixabay`.
- Never commit image binary files to git. Manifest entries only.
