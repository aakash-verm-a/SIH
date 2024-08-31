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

import tempfile
import shutil

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

        self.stops, self.names = extract_stop_info("C:/Users/aakas/Downloads/GTFS/stops - Copy (3).csv")
        self.routes = get_trip_stops("C:/Users/aakas/Downloads/GTFS/stop_times - Copy (2).csv")

        my_set = set()

        for road in self.routes:
            my_set.update(self.routes[road])

        self.keys_to_remove = [key for key in self.stops.keys() if key not in my_set]

        self.filter_delhi_data()

        self.gdf_roads = self.fetch_road_data(self.bbox)
        self.G = self.create_graph_from_roads(self.gdf_roads)

        self.colors = ['blue', 'green', 'red', 'purple', 'orange', 'brown', 'pink']
        self.map = None  # Initialize the map attribute


    def read_csv_a(self, file_path):
        drivers = []
        with open(file_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                drivers.append(row)
        return drivers

    def organize_drivers_by_zone(self, drivers):
        zone_drivers = defaultdict(list)
        for driver in drivers:
            zone_drivers[driver['Zone']].append(driver)
        return zone_drivers

    def assign_drivers_to_buses(self, zone_drivers, buses):
        assignments = {}
        for zone, drivers in zone_drivers.items():
            if zone in buses:
                available_buses = buses[zone]
                for i, driver in enumerate(drivers):
                    if i < len(available_buses):
                        bus = available_buses[i]
                        assignments[driver['Driver ID']] = {
                            'Driver Name': driver['Driver Name'],
                            'Bus Assigned': bus,
                            'Zone': zone
                        }
        return assignments

    def categorize_stops(self):
        buses = {
            "NE": [],
            "NW": [],
            "SE": [],
            "SW": []
        }
        
        for trip_id, lst in self.routes.items():
            lat, lon = self.stops[lst[0]]
            if float(lat) >= 28.6 and float(lon) >= 77.2:
                buses["NE"].append(trip_id)
            elif float(lat) >= 28.6 and float(lon) < 77.2:
                buses["NW"].append(trip_id)
            elif float(lat) < 28.6 and float(lon) >= 77.2:
                buses["SE"].append(trip_id)
            else:  # lat < 0 and lon < 0
                buses["SW"].append(trip_id)
        
        return buses

    def update_driver_assignments(self, csv_file):
        dri = self.read_csv_a(csv_file)
        zone_drivers = self.organize_drivers_by_zone(dri)
        assignments = self.assign_drivers_to_buses(zone_drivers, self.categorize_stops())

        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, newline='')
        
        try:
            with open(csv_file, 'r') as csvfile, temp_file:
                reader = csv.DictReader(csvfile)
                fieldnames = reader.fieldnames
                
                writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                writer.writeheader()

                print(assignments)
                
                for row in reader:
                    driver_id = row['Driver ID']
                    if driver_id in assignments:
                        # Update the Bus Assigned field
                        row['Bus Assigned'] = assignments[driver_id]['Bus Assigned']
                        # Update the Zone field if it exists in the assignment
                        if 'Zone' in assignments[driver_id]:
                            row['Zone'] = assignments[driver_id]['Zone']
                    writer.writerow(row)
            
            # Replace the original file with the updated temp file
            shutil.move(temp_file.name, csv_file)
            print(f"CSV file '{csv_file}' has been successfully updated.")
        
        except Exception as e:
            print(f"An error occurred: {e}")
            os.unlink(temp_file.name)  # Delete the temp file in case of error
            print("The original file was not modified.")


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
        self.manager.update_driver_assignments("C:/Users/aakas/Downloads/driver_details.csv")
        print("Running Bus Routing System...")
        map_path = self.manager.save_map()
        return map_path

@app.route('/')
def home():
    system = BusRoutingSystem()
    map_path = system.run()
    return render_template('index.html', map_path=map_path)

# Route to display the generated map
@app.route('/map')
def display_map():
    return render_template('delhi_bus_routes_map.html')

if __name__ == "__main__":
    app.run(debug=True)
