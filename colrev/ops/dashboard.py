#! /usr/bin/env python3
"""CoLRev dashboard operation: track project progress through dashboard"""
from __future__ import annotations

import dash
from dash import Dash
from dash import html

# pylint: disable=too-few-public-methods


class Dashboard:
    """Dashboard class"""

    def make_dashboard(self) -> Dash:
        """creates dashboard header and general structure"""
        app = Dash(__name__, use_pages=True)

        app.layout = html.Div(
            [
                html.Div(
                    [
                        html.Img(src="assets/favicon.ico", className="logo"),
                        html.H1(children="Dashboard", className="header-title"),
                        html.H2(
                            children="make progress visible",
                            className="header-subtitle",
                        ),
                    ],
                    className="header",
                ),
                dash.page_container,
            ]
        )

        return app


def main() -> None:
    """Main method for the dashboard"""

    dashboard = Dashboard()
    app = dashboard.make_dashboard()
    app.run_server(debug=True)
