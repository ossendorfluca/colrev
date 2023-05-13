#! /usr/bin/env python
"""Checker for year-format."""
from __future__ import annotations

import re

import colrev.qm.quality_model
import colrev.record

# pylint: disable=too-few-public-methods


class YearFormatChecker:
    """The YearFormatChecker"""

    def __init__(self, quality_model: colrev.qm.quality_model.QualityModel) -> None:
        self.quality_model = quality_model

    def run(self, *, record: colrev.record.Record) -> None:
        """Run the year-format checks"""

        if "year" not in record.data:
            return

        if not re.match(r"^\d{4}$", record.data["year"]):
            record.add_masterdata_provenance_note(key="year", note="year-format")


def register(quality_model: colrev.qm.quality_model.QualityModel) -> None:
    """Register the checker"""
    quality_model.register_checker(YearFormatChecker(quality_model))
