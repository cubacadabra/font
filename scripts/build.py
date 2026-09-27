#!/usr/bin/env python3
"""Build the fonts, vector proofs, and versioned distribution. OFL-1.1."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import string
import zipfile

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
import pathops

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("alphabet", ROOT / "sources/alphabet.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ALPHABET = MODULE.ALPHABET

VERSION = "0.1.0"
FONT_VERSION = "0.100"
UPM = 1000
CELL = 750
STROKE = 20
TIMESTAMP = 3873312000  # 2026-09-27 00:00:00 UTC, seconds since 1904.
VENDOR_SHA256 = "41b22bc8f0b51f932825d37bc55b5eb6ba67dfe599a626e4aff2b43b624f9f8c"
EXTRA_CHARACTERS = "\u00a0¡¢£¤¥¦§©«¬®°±²³¶·¹»¼½¾¿×÷–—‘’‚“”„†‡•…‰‹›€™−≠≤≥′″"


def stroked_path(points, closed=False, square=False):
    path = pathops.Path()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    if closed:
        path.close()
    path.stroke(STROKE,
                pathops.LineCap.BUTT_CAP if square else pathops.LineCap.ROUND_CAP,
                pathops.LineJoin.MITER_JOIN, 4)
    path.convertConicsToQuads(0.1)
    return path


def letter_glyph(letter):
    border = stroked_path([(0, 0), (CELL, 0), (CELL, CELL), (0, CELL)],
                          closed=True, square=True)
    for polyline in ALPHABET[letter]:
        points = [(x * CELL, (1 - y) * CELL) for x, y in polyline]
        closed = points[0] == points[-1]
        border.addPath(stroked_path(points[:-1] if closed else points, closed))
    # Merge every intersection before export; fonts contain filled outlines,
    # not SVG strokes or overlapping contours within a glyph.
    outline = pathops.simplify(border, clockwise=True)
    # Clip pointed diagonal joins to the square's outer extent.
    clip = pathops.Path()
    h = STROKE / 2
    clip.moveTo(-h, -h)
    clip.lineTo(CELL + h, -h)
    clip.lineTo(CELL + h, CELL + h)
    clip.lineTo(-h, CELL + h)
    clip.close()
    outline = pathops.op(outline, clip, pathops.PathOp.INTERSECTION,
                         fix_winding=True, clockwise=True)
    pen = TTGlyphPen(None)
    outline.draw(Cu2QuPen(pen, max_err=0.25))
    return pen.glyph()


def imported_glyph(source, name, scale):
    glyph_set = source.getGlyphSet()
    recording = DecomposingRecordingPen(glyph_set)
    glyph_set[name].draw(recording)
    pen = TTGlyphPen(None)
    recording.replay(TransformPen(pen, (scale, 0, 0, scale, 0, 0)))
    glyph = pen.glyph()
    glyph.recalcBounds(None)
    advance = round(source["hmtx"][name][0] * scale)
    # Keep punctuation clear of a neighboring letter's overhanging box edge.
    if glyph.numberOfContours:
        offset = max(0, 35 - glyph.xMin)
        if offset:
            glyph.coordinates.translate((offset, 0))
            glyph.recalcBounds(None)
        advance = max(advance + offset, glyph.xMax + 35)
    return glyph, (advance, getattr(glyph, "xMin", 0))


def build_font():
    vendor = ROOT / "sources/vendor/Arimo-Regular.ttf"
    if hashlib.sha256(vendor.read_bytes()).hexdigest() != VENDOR_SHA256:
        raise ValueError("Arimo source checksum differs from the pinned version")
    source = TTFont(vendor)
    scale = CELL / source["OS/2"].sCapHeight
    source_cmap = source.getBestCmap()
    glyphs, metrics, cmap = {}, {}, {}
    glyphs[".notdef"], metrics[".notdef"] = imported_glyph(source, ".notdef", scale)
    for character in string.ascii_uppercase:
        glyphs[character] = letter_glyph(character)
        metrics[character] = (CELL, -STROKE // 2)
        cmap[ord(character)] = character
        cmap[ord(character.lower())] = character
    for codepoint in sorted(set(range(32, 127)) | {ord(c) for c in EXTRA_CHARACTERS}):
        if codepoint in cmap:
            continue
        if codepoint not in source_cmap:
            raise ValueError(f"Arimo has no U+{codepoint:04X}")
        name = "space" if codepoint == 32 else f"uni{codepoint:04X}"
        if codepoint in (32, 160):
            glyphs[name] = TTGlyphPen(None).glyph()
            metrics[name] = (CELL // 2, 0)
        else:
            glyphs[name], metrics[name] = imported_glyph(source, source_cmap[codepoint], scale)
        cmap[codepoint] = name

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(list(glyphs))
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    # Include all punctuation extents so platforms do not clip tall symbols.
    top = max(g.yMax for g in glyphs.values() if g.numberOfContours)
    bottom = min(g.yMin for g in glyphs.values() if g.numberOfContours)
    ascent, descent = max(950, top), min(-250, bottom)
    fb.setupHorizontalHeader(ascent=ascent, descent=descent, lineGap=0)
    license_text = (ROOT / "OFL.txt").read_text()
    copyright_text = license_text.split("\n\n", 1)[0]
    fb.setupNameTable({
        "familyName": "Cubacadabra", "styleName": "Regular",
        "uniqueFontIdentifier": f"Cubacadabra:Regular:{FONT_VERSION}",
        "fullName": "Cubacadabra Regular", "psName": "Cubacadabra-Regular",
        "version": f"Version {FONT_VERSION}",
        "typographicFamily": "Cubacadabra", "typographicSubfamily": "Regular",
        "copyright": copyright_text,
        "manufacturer": "Cubacadabra Project Authors",
        "designer": "Cubacadabra Project Authors; Arimo Project Authors (symbols)",
        "description": "Connected square display alphabet from the Cubacadabra artwork. "
                       "Uppercase and lowercase share glyphs. Use zero letter spacing. "
                       "Numerals and punctuation adapted from Arimo Regular.",
        "licenseDescription": license_text,
        "licenseInfoURL": "https://openfontlicense.org",
    })
    fb.setupOS2(version=4, sTypoAscender=ascent, sTypoDescender=descent, sTypoLineGap=0,
                usWinAscent=ascent, usWinDescent=-descent,
                sxHeight=CELL, sCapHeight=CELL, usWeightClass=400,
                usWidthClass=5, fsType=0, fsSelection=(1 << 6) | (1 << 7),
                achVendID="NONE")
    fb.setupPost(underlinePosition=-120, underlineThickness=20)
    fb.setupMaxp()
    fb.font["head"].fontRevision = float(FONT_VERSION)
    fb.font["head"].created = TIMESTAMP
    fb.font["head"].modified = TIMESTAMP
    fb.font.recalcTimestamp = False
    fb.font["gasp"] = newTable("gasp")
    fb.font["gasp"].gaspRange = {65535: 0x000A}  # Smooth unhinted display outlines.
    destination = ROOT / "fonts"
    destination.mkdir(exist_ok=True)
    ttf = destination / "Cubacadabra-Regular.ttf"
    fb.save(ttf)
    fb.font.flavor = "woff2"
    fb.save(destination / "Cubacadabra-Regular.woff2")
    source.close()
    return TTFont(ttf)


def svg_text(font, text, x, baseline, size):
    glyph_set, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = size / UPM
    paths, cursor = [], x
    for character in text:
        name = cmap.get(ord(character), ".notdef")
        pen = SVGPathPen(glyph_set)
        glyph_set[name].draw(pen)
        paths.append(f'<path transform="translate({cursor:g} {baseline:g}) '
                     f'scale({scale:g} {-scale:g})" d="{pen.getCommands()}"/>')
        cursor += font["hmtx"][name][0] * scale
    return "\n".join(paths)


def build_proofs(font):
    directory = ROOT / "specimen"
    directory.mkdir(exist_ok=True)
    wordmark = svg_text(font, "cubacadabra", 20, 150, 160)
    (directory / "cubacadabra.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1360 180" '
        'role="img" aria-label="Cubacadabra in connected square letters">\n'
        '<title>Cubacadabra</title>\n<g fill="currentColor">\n' + wordmark + '\n</g></svg>\n')
    tiles = []
    for index, character in enumerate(string.ascii_uppercase):
        x, y = 24 + (index % 7) * 145, 140 + (index // 7) * 177
        tiles.append(svg_text(font, character, x, y, 160))
        tiles.append(f'<text x="{x + 60}" y="{y + 29}" text-anchor="middle" '
                     f'font-family="Arial, sans-serif" font-size="20">{character}</text>')
    (directory / "alphabet.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 728" '
        'role="img" aria-label="Cubacadabra alphabet A through Z">\n'
        '<title>Cubacadabra alphabet</title><g fill="currentColor">\n'
        + "\n".join(tiles) + '\n</g></svg>\n')
    import unicodedata
    (directory / "characters.txt").write_text("".join(
        f"U+{codepoint:04X}  {chr(codepoint)}  {unicodedata.name(chr(codepoint))}\n"
        for codepoint in sorted(font.getBestCmap())))
    # Raster proofs come from the compiled TTF through FreeType, so they also
    # exercise the shipping font rather than only the source geometry.
    from PIL import Image, ImageDraw, ImageFont
    face = ImageFont.truetype(str(ROOT / "fonts/Cubacadabra-Regular.ttf"), 160)
    label = ImageFont.truetype(str(ROOT / "sources/vendor/Arimo-Regular.ttf"), 24)
    word_image = Image.new("RGB", (1360, 180), "white")
    ImageDraw.Draw(word_image).text((20, 150), "cubacadabra", font=face,
                                   anchor="ls", fill="black")
    word_image.save(directory / "cubacadabra.png")
    alphabet_image = Image.new("RGB", (1040, 728), "white")
    draw = ImageDraw.Draw(alphabet_image)
    for index, character in enumerate(string.ascii_uppercase):
        x, y = 24 + (index % 7) * 145, 140 + (index // 7) * 177
        draw.text((x, y), character, font=face, anchor="ls", fill="black")
        draw.text((x + 60, y + 16), character, font=label, anchor="mt", fill="black")
    alphabet_image.save(directory / "alphabet.png")


def package_release():
    # The archive is reproducible and includes everything needed to preview,
    # install, self-host, and rebuild without downloading the upstream font.
    inputs = [ROOT / p for p in ("README.md", "FONTLOG.md", "OFL.txt", "requirements.txt")]
    for directory in ("fonts", "sources", "scripts", "specimen"):
        inputs.extend(p for p in (ROOT / directory).rglob("*")
                      if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    inputs.extend([ROOT / "alpha.png", ROOT / "11.png"])
    missing = [str(p.relative_to(ROOT)) for p in inputs if not p.exists()]
    if missing:
        print("Release archive deferred; missing " + ", ".join(missing))
        return
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    archive = release / f"Cubacadabra-{VERSION}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(inputs):
            info = zipfile.ZipInfo(f"Cubacadabra-{VERSION}/{path.relative_to(ROOT)}",
                                   (2026, 9, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, path.read_bytes())
    checksum_paths = sorted((ROOT / "fonts").glob("*")) + [archive]
    (release / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}\n"
        for p in checksum_paths if p.is_file()))
    print(f"Packaged {archive.relative_to(ROOT)}")


if __name__ == "__main__":
    font = build_font()
    build_proofs(font)
    print(f"Built Cubacadabra {VERSION}: {len(font.getBestCmap())} Unicode characters, "
          f"{len(font.getGlyphOrder())} glyphs")
    package_release()
