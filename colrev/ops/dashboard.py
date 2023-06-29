#! /usr/bin/env python3
"""CoLRev dashboard operation: to track project progress through dashboard"""
from __future__ import annotations


import pandas as pd
from dash import Dash, dcc, html, Input, Output, dash_table, State
import bibtexparser


class Dashboard():
    
    def filteringData ():
        with open(
            "./data/records.bib"
        ) as bibtex_file:  # changing file format to csv for pandas
            bib_database = bibtexparser.load(bibtex_file)
            if not bib_database.entries:  # checking if bib_database file is empty
                raise Exception("Die Datei 'records.bib' ist leer.") # throwing Exception 
        df = pd.DataFrame(bib_database.entries)
        df.to_csv("./data/records.csv", index = True)
        data = (pd.read_csv("./data/records.csv").query("colrev_status == 'rev_synthesized'"))
        data.rename(columns={'Unnamed: 0':'index'}, inplace=True)
        return data

    def makeTable(self):
        
        data= Dashboard.filteringData()
        

        for title in data:
            if title != "title" and title != "author" and title != "year":
                data.pop(title)

        app = Dash(__name__)                                # initializing the dashboard app

        app.layout = html.Div(                              # defining th content
            children=[
                html.Div(
                children=[
                    html.Img(src="assets/favicon.ico", className="logo"), 
                    html.H1(children="DASHBOARD", className= "header-title")], className="header"),

                html.Div(children=[    
                    html.H1(children="CURRENTLY SYNTHESIZED RECORDS", className="table-header"),

                    html.Div(children=[
                        dcc.Dropdown(
                            id="sortby",
                            options=["index","year", "author (alphabetically)"],
                        )])
                        ], className="flexboxtable"),
                html.Div(children=[
                    dcc.Input(
                        type="text", id="searchbar", value=""
                    ),
                    html.Button('Search!', id='searchbutton')
                ]), 
                html.Br(),                     
                html.Div([
                    dash_table.DataTable(data = data.to_dict('records'),id = "table")
                ]),
                html.Div(id="table_empty", children= []) 
                        
            ])

        @app.callback(
            Output("table", "data"),
            Output("table_empty", "children"),
            State("searchbar", "value"),
            Input("searchbutton", "n_clicks"),
        )
        def update_table(value, n_clicks):
            
            
            data2 = data.copy(deep = True).to_dict('records')

            output = ""

            for row in data.to_dict('records'):
                found = False
                for key in row:
                    if value.lower().strip() in str(row[key]).lower():
                        found = True
                
                if found is False:  
                    data2.remove(row)
                
                if not data2:
                    output = "no records found for your search"
                    
            return data2, output
            
        return app




def main() -> None:

    dashboard = Dashboard()

    try:
        app = dashboard.makeTable()
        app.run_server(debug=True)
    except Exception as e: # catching Exception
        print("Fehler:", str(e)) # print error

   