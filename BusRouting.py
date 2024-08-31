from flask import Flask, render_template, send_file
import os

import requests
import geopandas as gpd
from shapely.geometry import LineString, Point
import folium
import networkx as nx
import pandas as pd
import random
import csv
from collections import defaultdict

# Existing functions to extract stop info and get trip stops
def extract_stop_info(csv_file_path):
    stop_info = {}
    name_info = {}

    with open(csv_file_path, mode='r', newline='') as file:
        reader = csv.DictReader(file)
        for row in reader:
            stop_info[row['stop_id']] = (row['stop_lat'], row['stop_lon'])
            name_info[row['stop_id']] = row['stop_name']

    return stop_info, name_info

def get_trip_stops(csv_file_path):
    trip_stops = defaultdict(list)

    with open(csv_file_path, mode='r', newline='') as file:
        reader = csv.DictReader(file)
        for row in reader:
            trip_id = row['trip_id']
            stop_id = row['stop_id']
            trip_stops[trip_id].append(stop_id)

    return trip_stops

# Define the Flask app
app = Flask(__name__)

class RouteManager:
    def __init__(self):
        self.bbox = (77.0, 28.4, 77.4, 28.8)

        self.stops, self.names = extract_stop_info("F:\CollegeStudy\SIH\stops - Copy (3).csv.xls")
        self.routes = get_trip_stops("F:\CollegeStudy\SIH\stop_times - Copy (2).csv.xls")

        my_set = set()

        for road in self.routes:
            my_set.update(self.routes[road])

        self.keys_to_remove = [key for key in self.stops.keys() if key not in my_set]

        self.filter_delhi_data()

        self.gdf_roads = self.fetch_road_data(self.bbox)
        self.G = self.create_graph_from_roads(self.gdf_roads)

        self.colors = ['blue', 'green', 'red', 'purple', 'orange', 'brown', 'pink']
        self.map = None  # Initialize the map attribute

    def filter_delhi_data(self):
        self.stops = {k: v for k, v in self.stops.items() 
                      if self.bbox[0] <= float(v[1]) <= self.bbox[2] and 
                         self.bbox[1] <= float(v[0]) <= self.bbox[3]}
        self.routes = {k: [stop for stop in v if stop in self.stops] for k, v in self.routes.items()}
        self.routes = {k: v for k, v in self.routes.items() if len(v) >= 2}

    def fetch_road_data(self, bbox):
        overpass_url = "http://overpass-api.de/api/interpreter"
        overpass_query = f"""
        [out:json];
        way["highway"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
        out geom;
        """
        response = requests.get(overpass_url, params={'data': overpass_query})
        data = response.json()

        roads = []
        for row in self.routes:
            coords = [self.stops[node] for node in self.routes[row]]
            roads.append(LineString(coords))

        gdf_roads = gpd.GeoDataFrame(geometry=roads, crs="EPSG:4326")
        return gdf_roads

    def create_graph_from_roads(self, gdf_roads):
        G = nx.Graph()
        for _, row in gdf_roads.iterrows():
            coords = list(row.geometry.coords)
            for i in range(len(coords) - 1):
                G.add_edge(coords[i], coords[i + 1], weight=row.geometry.length)
        return G

    def find_shortest_path(self, start, end):
        start_node = min(self.G.nodes, key=lambda x: Point(x).distance(Point(start)))
        end_node = min(self.G.nodes, key=lambda x: Point(x).distance(Point(end)))
        path = nx.shortest_path(self.G, source=start_node, target=end_node, weight='weight')
        return path

    def create_map(self):
        center = [(self.bbox[1] + self.bbox[3]) / 2, (self.bbox[0] + self.bbox[2]) / 2]
        self.map = folium.Map(location=center, zoom_start=11)
        folium.TileLayer('OpenStreetMap').add_to(self.map)

        for stop, coord in self.stops.items():
            if stop not in self.keys_to_remove:
                folium.Marker(location=coord, popup=self.names.get(stop, stop), 
                              icon=folium.Icon(color='red', icon='info-sign')).add_to(self.map)

        for route_id, stops in self.routes.items():
            path_coords = []
            for i in range(len(stops) - 3):
                start = self.stops[stops[i]]
                end = self.stops[stops[i + 1]]
                path = self.find_shortest_path(start, end)
                path_coords.extend(path)
            path_coords = list(dict.fromkeys(path_coords))
            folium.PolyLine(locations=path_coords, color=random.choice(self.colors), 
                            weight=4, opacity=0.8, popup=f"Route {route_id}").add_to(self.map)

        folium.LayerControl().add_to(self.map)
        folium.Rectangle(bounds=[(self.bbox[1], self.bbox[0]), (self.bbox[3], self.bbox[2])], 
                         color="red", fill=False, weight=2).add_to(self.map)

    def save_map(self):
        # Save the map to a temporary file
        self.create_map()
        map_path = "templates/delhi_bus_routes_map.html"
        self.map.save(map_path)
        return map_path

class BusRoutingSystem:
    def __init__(self):
        print("Initializing Bus Routing System...")
        self.manager = RouteManager()

    def run(self):
        print("Running Bus Routing System...")
        map_path = self.manager.save_map()
        return map_path

@app.route('/')
def home():
    system = BusRoutingSystem()
    map_path = system.run()
    return render_template('a.html', map_path=map_path)

# Route to display the generated map
@app.route('/map')
def display_map():
    return render_template('delhi_bus_routes_map.html')

if __name__ == "__main__":
    app.run(debug=True)
