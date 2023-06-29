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
                html.Div(children=[
                    html.Img(src="assets/favicon.ico", className="logo"), 
                    html.H1(children="DASHBOARD", className= "header-title")], className="header"),

                html.Div(className = "options", children=[
                    dcc.Dropdown(
                        id="sortby",
                        options=["index","year", "author (alphabetically)"], 
                        placeholder="Sort by..."
                    ),
                    dcc.Input(type="text", id="search", value="", placeholder="  Search for..."),
                ]),
                html.H1(children="currently synthesized records:", id="headline"),                   
                html.Div([
                    dash_table.DataTable(data = data.to_dict('records'),id = "table", 
                    style_cell = {'font-family': 'Lato, sans-serif','font-size': '20px','text-align': 'left'},
                    style_header = {'font-weight': 'bold'})
                ]),
                html.Div(id="table_empty", children= []) 
                        
            ])

        @app.callback(
            Output("table", "data"),
            Output("table_empty", "children"),
            Input("search", "value"),
        )
        def update_table(value):
            

            
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
