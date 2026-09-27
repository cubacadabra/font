#!/usr/bin/env python3
"""Verify the built font's coverage, geometry, metrics, and real raster output."""

from pathlib import Path
import hashlib
import io
import shutil
import string
import subprocess
import zipfile

from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def verify():
    ttf_path = ROOT / "fonts/Cubacadabra-Regular.ttf"
    ttf = TTFont(ttf_path, checkChecksums=2)
    web = TTFont(ROOT / "fonts/Cubacadabra-Regular.woff2", checkChecksums=2)
    # Decode and compare the two shipping formats, including all outline data.
    assert ttf.getBestCmap() == web.getBestCmap()
    assert ttf["hmtx"].metrics == web["hmtx"].metrics
    for name in ttf.getGlyphOrder():
        assert ttf["glyf"][name].getCoordinates(ttf["glyf"])[0] == web["glyf"][name].getCoordinates(web["glyf"])[0]
    cmap = ttf.getBestCmap()
    assert all(cp in cmap for cp in range(32, 127)), "Missing printable ASCII"
    assert len(cmap) == 144
    assert ttf.getGlyphOrder()[0] == ".notdef"
    assert ttf["OS/2"].fsType == 0
    assert ttf["OS/2"].version >= 4
    assert ttf["name"].getDebugName(1) == "Cubacadabra"
    assert ttf["name"].getDebugName(2) == "Regular"
    assert "SIL OPEN FONT LICENSE" in ttf["name"].getDebugName(13)
    assert not ({"kern", "GPOS", "GSUB"} & set(ttf.keys())), "Joins must work without shaping features"
    for glyph in ttf["glyf"].glyphs.values():
        if glyph.numberOfContours:
            assert glyph.yMax <= ttf["OS/2"].usWinAscent
            assert glyph.yMin >= -ttf["OS/2"].usWinDescent
    letter_outlines = set()
    for letter in string.ascii_uppercase:
        name = cmap[ord(letter)]
        assert cmap[ord(letter.lower())] == name
        assert ttf["hmtx"][name] == (750, -10)
        glyph = ttf["glyf"][name]
        assert (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax) == (-10, -10, 760, 760)
        letter_outlines.add(glyph.compile(ttf["glyf"]))
    assert len(letter_outlines) == 26, "Two letters accidentally share a design"

    # FreeType renders the finished file, independently of the outline builder.
    font = ImageFont.truetype(str(ttf_path), 1000)
    assert font.getlength("cubacadabra") == 8250
    assert font.getlength("cubacadabra") == font.getlength("CUBACADABRA")
    drawing = Image.new("L", (1600, 900), 255)
    ImageDraw.Draw(drawing).text((40, 800), "DD", font=font, anchor="ls", fill=0)
    # At a height clear of D's inner stroke, both outer edges and the shared
    # edge must have identical thickness; two side-by-side strokes would fail.
    left = drawing.crop((20, 100, 60, 180))
    middle = drawing.crop((770, 100, 810, 180))
    right = drawing.crop((1520, 100, 1560, 180))
    assert ImageChops.difference(left, middle).getbbox() is None, "Doubled shared border"
    assert ImageChops.difference(left, right).getbbox() is None, "Unequal end border"
    assert left.getextrema() == (0, 255)
    web.flavor = None
    buffer = io.BytesIO()
    web.save(buffer)
    buffer.seek(0)
    web_font = ImageFont.truetype(buffer, 1000)
    assert bytes(web_font.getmask("cubacadabra")) == bytes(font.getmask("cubacadabra"))

    hb = shutil.which("hb-shape")
    if hb:
        for shaper in ("ot", "coretext"):
            available = subprocess.check_output([hb, "--list-shapers"], text=True)
            if shaper not in available:
                continue
            shaped = subprocess.check_output([hb, str(ttf_path), "cubacadabra",
                                               f"--shapers={shaper}", "--verify"], text=True)
            assert shaped.count("+750") == 11, shaped
            print(f"PASS: {shaper} shaping, 11 glyphs at 750 units each")
    else:
        print("SKIP: HarfBuzz/CoreText shaping (hb-shape unavailable)")

    sums = ROOT / "release/SHA256SUMS.txt"
    assert sums.exists(), "Release checksums missing; run build.py"
    for line in sums.read_text().splitlines():
        expected, relative = line.split("  ", 1)
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    with zipfile.ZipFile(ROOT / "release/Cubacadabra-0.1.0.zip") as archive:
        assert archive.testzip() is None
        for path in ("fonts/Cubacadabra-Regular.ttf", "fonts/Cubacadabra-Regular.woff2",
                     "OFL.txt", "specimen/index.html", "scripts/verify.py", "sources/alphabet.py"):
            assert archive.read(f"Cubacadabra-0.1.0/{path}") == (ROOT / path).read_bytes()
    print("PASS: 144 characters; 26 distinct letter designs; matching TTF/WOFF2; "
          "unclipped metrics; equal shared borders; release integrity")


if __name__ == "__main__":
    verify()
