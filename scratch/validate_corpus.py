import os
import re
import sys
import yaml

MAX_SECTION_CHARS = 2200

def validate_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    errors = []
    # Check front matter
    fm_match = re.match(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", content, re.S)
    if not fm_match:
        errors.append("Missing or malformed YAML front matter")
        return errors

    fm_raw = fm_match.group(1)
    body = fm_match.group(2)

    try:
        meta = yaml.safe_load(fm_raw)
        if not isinstance(meta, dict):
            errors.append("Front matter is not a YAML dict")
    except Exception as e:
        errors.append(f"YAML error: {e}")
        return errors

    # Check required fields
    for field in ['title', 'kind', 'source', 'scope', 'category']:
        if field not in meta or not str(meta[field]).strip():
            errors.append(f"Missing required field: {field}")

    # Check sections
    sections = re.split(r"^## +(.+?)[ \t]*$", body, flags=re.M)
    # sections[0] is preamble before first ##
    preamble = sections[0].strip()
    # Check for prose before first ## (only optional # H1 allowed)
    non_h1 = [line for line in preamble.splitlines() if not line.strip().startswith("# ") and line.strip()]
    if non_h1:
        errors.append(f"Prose before first ## heading: {non_h1[0][:60]}...")

    num_sections = (len(sections) - 1) // 2
    if num_sections == 0:
        errors.append("No ## sections found")

    for i in range(num_sections):
        heading = sections[1 + 2*i].strip()
        sec_text = sections[2 + 2*i].strip()
        char_len = len(sec_text)
        if char_len == 0:
            errors.append(f"Section '{heading}' has no body")
        elif char_len > MAX_SECTION_CHARS:
            errors.append(f"Section '{heading}' is {char_len} chars (exceeds {MAX_SECTION_CHARS} limit by {char_len - MAX_SECTION_CHARS})")

    return errors

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'docs/the_spoin_universe/corpus/astronomy/physics/astronomy'
    if os.path.isfile(target):
        files = [target]
    else:
        files = [os.path.join(target, f) for f in os.listdir(target) if f.endswith('.md')]

    all_passed = True
    for fpath in files:
        errs = validate_file(fpath)
        if errs:
            all_passed = False
            print(f"FAIL: {fpath}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"PASS: {fpath}")

    sys.exit(0 if all_passed else 1)
