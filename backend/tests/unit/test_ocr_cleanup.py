"""Unit tests for OCR artifact normalisation.

Every case here comes from a real 22-page SOP whose text was converted to
outlines on export, so it had to be rasterised and OCR'd. The artifacts
are not hypothetical -- they are what Tesseract actually produced.

The bullet artifact is the one that matters. OCR read every "•" as the
letter "e", so procedure lines came out as "e Product Transfers (PT)".
That single character trips three independent defences, each written to
catch genuinely corrupted text:

  * checklist_chunker recognises "-", "*", "+" and numbers, so no
    procedure was chunked as a checklist at all;
  * search.py's _FRAGMENT_START_RE cuts any lowercase-starting chunk's
    score to 35%, treating it as a mid-word truncation;
  * package_builder._starts_cleanly drops such chunks from the answer
    candidates entirely.

Repairing the artifact once, here, is the fix. Loosening those three
safeguards is not -- they exist because genuinely broken chunks make
terrible answers.
"""

from __future__ import annotations

from app.documents.ocr_cleanup import clean_ocr_pages, clean_ocr_text


class TestBulletRepair:
    def test_e_bullet_becomes_a_list_marker(self):
        assert clean_ocr_text("e Product Transfers (PT)") == "- Product Transfers (PT)"

    def test_indented_bullet_is_repaired(self):
        assert clean_ocr_text("   e Fund Switches") == "- Fund Switches"

    def test_other_misread_bullet_glyphs_are_repaired(self):
        for glyph in ("•", "·", "o", "©"):
            assert clean_ocr_text(f"{glyph} Rate Securing") == "- Rate Securing"

    def test_every_bullet_in_a_block_is_repaired(self):
        raw = "The process ensures:\ne Client retention\ne Regulatory compliance"
        assert clean_ocr_text(raw) == (
            "The process ensures:\n- Client retention\n- Regulatory compliance"
        )


class TestBulletRepairDoesNotOverreach:
    """The repair must not damage text that was never broken."""

    def test_a_sentence_starting_with_e_is_untouched(self):
        text = "e.g. a product transfer requires no fee."
        assert clean_ocr_text(text) == text

    def test_a_word_starting_with_e_is_untouched(self):
        text = "Equity is the difference between value and balance."
        assert clean_ocr_text(text) == text

    def test_mid_sentence_e_is_untouched(self):
        text = "The rate e was confirmed by the lender."
        assert clean_ocr_text(text) == text

    def test_a_lone_e_with_no_following_text_is_untouched(self):
        assert clean_ocr_text("e") == "e"

    def test_clean_document_passes_through_unchanged(self):
        text = (
            "Step 1.1 - Identify Upcoming Expiries\n"
            "- CRM diary reminders\n"
            "- Lender maturity reports\n\n"
            "Typically, clients should be contacted 4-6 months before expiry."
        )
        assert clean_ocr_text(text) == text


class TestNoiseLines:
    """The final page is a flowchart; OCR read its arrows as stray
    letters on their own lines."""

    def test_arrow_artifact_lines_are_dropped(self):
        raw = "AML Check\nL\nResearch Rates\nJ\nSecure Rate"
        assert clean_ocr_text(raw) == "AML Check\nResearch Rates\nSecure Rate"

    def test_single_character_noise_is_dropped(self):
        assert clean_ocr_text("Secure Rate\n|\n_\nSend Offer") == (
            "Secure Rate\nSend Offer"
        )

    def test_real_single_word_lines_survive(self):
        """A short heading is not noise."""
        raw = "Objective\nTo contact clients approaching expiry."
        assert clean_ocr_text(raw) == raw

    def test_a_numbered_step_is_not_noise(self):
        assert clean_ocr_text("1.\nSubmitted to Provider") == (
            "1.\nSubmitted to Provider"
        )


class TestDoubledHeadings:
    """Rendered headings were captured twice with no separator."""

    def test_exact_doubling_is_collapsed(self):
        assert clean_ocr_text("Mortgage Rate SecuredMortgage Rate Secured") == (
            "Mortgage Rate Secured"
        )

    def test_second_real_example_is_collapsed(self):
        raw = "Mortgage Review AppointmentMortgage Review Appointment"
        assert clean_ocr_text(raw) == "Mortgage Review Appointment"

    def test_a_line_that_merely_repeats_a_word_is_untouched(self):
        text = "Review the review diary dates"
        assert clean_ocr_text(text) == text

    def test_a_genuinely_repeated_short_token_is_untouched(self):
        """Doubling only collapses when the halves are substantial, so a
        line like "1010" is not mangled into "10"."""
        assert clean_ocr_text("1010") == "1010"


class TestPages:
    def test_blank_pages_are_dropped(self):
        pages = ["Page one text", "   ", "", "Page four text"]
        assert clean_ocr_pages(pages) == ["Page one text", "Page four text"]

    def test_pages_that_become_empty_after_cleanup_are_dropped(self):
        """The flowchart page reduces to nothing but arrow artifacts."""
        assert clean_ocr_pages(["Real content", "L\nJ\n|"]) == ["Real content"]

    def test_each_page_is_cleaned(self):
        assert clean_ocr_pages(["e First", "e Second"]) == ["- First", "- Second"]

    def test_no_pages_yields_no_pages(self):
        assert clean_ocr_pages([]) == []


class TestOcrPageByPage:
    """ocr_pdf_pages used to call convert_from_path once for the whole
    document, materialising every page as a PIL image simultaneously --
    roughly 150-200MB for a 22-page PDF at the 200 DPI default. That
    survives the 512MB development cap but would very likely OOM against
    the ~200MB production figure in CLAUDE.md rule 10, inside a detached
    batch process whose failure surfaces only as a document that never
    appears.
    """

    def _stub_pdf2image(self, monkeypatch, pages: int):
        import sys
        import types

        calls: list[dict] = []

        module = types.ModuleType("pdf2image")

        def convert_from_path(path, **kwargs):
            calls.append(kwargs)
            first = kwargs.get("first_page") or 1
            last = kwargs.get("last_page") or pages
            if first > pages:
                return []
            return [f"image-{n}" for n in range(first, min(last, pages) + 1)]

        module.convert_from_path = convert_from_path
        monkeypatch.setitem(sys.modules, "pdf2image", module)
        return calls

    def _stub_tesseract(self, monkeypatch, fail_on: str | None = None):
        from app.documents import ocr

        def image_to_string(image):
            if fail_on is not None and image == fail_on:
                raise RuntimeError("tesseract exploded")
            return f"text of {image}"

        # raising=False: pytesseract is an optional dependency, so on a
        # host without it ocr.py never binds the name at all.
        monkeypatch.setattr(ocr, "HAS_TESSERACT", True, raising=False)
        monkeypatch.setattr(
            ocr,
            "pytesseract",
            type("T", (), {"image_to_string": staticmethod(image_to_string)}),
            raising=False,
        )

    def test_one_conversion_call_per_page(self, monkeypatch, tmp_path):
        from app.documents import ocr

        calls = self._stub_pdf2image(monkeypatch, pages=3)
        self._stub_tesseract(monkeypatch)
        pdf = tmp_path / "d.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages = ocr.ocr_pdf_pages(pdf)

        assert len(pages) == 3
        # One call per page, plus a final probe that returns nothing --
        # discovering the document has ended requires asking for the page
        # after the last one.
        assert len(calls) == 4, "pages were not rendered one at a time"
        assert [c["first_page"] for c in calls] == [1, 2, 3, 4]
        # The property that actually bounds memory: no single call is ever
        # allowed to materialise more than one page.
        assert all(c["first_page"] == c["last_page"] for c in calls)

    def test_renders_at_300_dpi(self, monkeypatch, tmp_path):
        """200 is marginal for outlined text; 300 is the usual floor."""
        from app.documents import ocr

        calls = self._stub_pdf2image(monkeypatch, pages=1)
        self._stub_tesseract(monkeypatch)
        pdf = tmp_path / "d.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        ocr.ocr_pdf_pages(pdf)
        assert calls[0]["dpi"] == 300

    def test_page_cap_is_honoured(self, monkeypatch, tmp_path):
        """An unbounded loop inside the batch process is a denial of
        service waiting for a 500-page upload."""
        from app.documents import ocr

        self._stub_pdf2image(monkeypatch, pages=50)
        self._stub_tesseract(monkeypatch)
        pdf = tmp_path / "d.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages = ocr.ocr_pdf_pages(pdf, max_pages=5)
        assert len(pages) == 5

    def test_one_bad_page_does_not_fail_the_document(self, monkeypatch, tmp_path):
        from app.documents import ocr

        self._stub_pdf2image(monkeypatch, pages=3)
        self._stub_tesseract(monkeypatch, fail_on="image-2")
        pdf = tmp_path / "d.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages = ocr.ocr_pdf_pages(pdf)
        assert len(pages) == 3
        assert pages[1] == ""
        assert "image-1" in pages[0] and "image-3" in pages[2]
