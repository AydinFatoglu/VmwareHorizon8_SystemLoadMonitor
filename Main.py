import requests
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import socket
import uuid
import base64
from pyVmomi import vim
from pyVim import connect

# Disable SSL warnings (use only in test environments)
requests.packages.urllib3.disable_warnings()

# Horizon server hostnames
horizon_servers = ["https://HorizonVCS01FQDN", "https://HorizonVCS01FQDN"]

# vCenter server hostnames
vcenter_credentials = {
    "host_1": "VCENTER1FQDN",
    "host_2": "VCENTER2FQDN",
    "cluster_1": "CLS1",
    "cluster_2": "CLS2"
}

# API endpoints
auth_endpoint = '/rest/login'
desktop_pools_endpoint = '/rest/inventory/v2/desktop-pools'
machines_endpoint = '/rest/inventory/v1/machines'

# States to count
states_to_count = [
    "AVAILABLE", "CONNECTED", "DISCONNECTED", "DELETING",
    "PROVISIONING", "CUSTOMIZING", "ERROR"
]

# States display order
states_display_order = [
    "AVAILABLE", "CONNECTED", "DISCONNECTED", "DELETING",
    "PROVISIONING", "CUSTOMIZING", "ERROR"
]

# Session storage
sessions = {}

# Function to connect to vCenter
def connect_to_vcenter(host, user, password, port=443):
    try:
        service_instance = connect.SmartConnect(
            host=host,
            user=user,
            pwd=password,
            port=port,
            sslContext=None
        )
        return service_instance
    except vim.fault.InvalidLogin as e:
        print(f"Error connecting to vCenter: {e}")
        return None
    except Exception as e:
        print(f"Error connecting to vCenter: {e}")
        return None

# Function to get cluster performance metrics
def get_cluster_performance_metrics(service_instance, cluster_name):
    try:
        content = service_instance.RetrieveContent()
        cluster = None

        for obj in content.viewManager.CreateContainerView(content.rootFolder, [vim.ClusterComputeResource], recursive=True).view:
            if obj.name == cluster_name:
                cluster = obj
                break

        if cluster:
            total_memory_usage_mb = 0
            total_memory_capacity_mb = 0
            total_cpu_usage_mhz = 0
            total_cpu_capacity_mhz = 0
            host_data = []

            for host in cluster.host:
                summary = host.summary
                host_memory_usage_mb = summary.quickStats.overallMemoryUsage
                host_memory_capacity_mb = summary.hardware.memorySize / (1024 * 1024)  # Convert bytes to MB
                host_cpu_usage_mhz = summary.quickStats.overallCpuUsage  # CPU usage in MHz
                host_cpu_capacity_mhz = summary.hardware.cpuMhz * summary.hardware.numCpuCores  # Total CPU capacity in MHz

                host_data.append({
                    "name": host.name,
                    "used_memory_gb": host_memory_usage_mb / 1024,  # Convert MB to GB
                    "total_memory_gb": host_memory_capacity_mb / 1024,  # Convert MB to GB
                    "free_memory_gb": (host_memory_capacity_mb - host_memory_usage_mb) / 1024,  # Convert MB to GB
                    "cpu_usage_ghz": host_cpu_usage_mhz / 1000,  # Convert MHz to GHz
                    "cpu_capacity_ghz": host_cpu_capacity_mhz / 1000,  # Convert MHz to GHz
                    "cpu_free_ghz": (host_cpu_capacity_mhz - host_cpu_usage_mhz) / 1000  # Convert MHz to GHz
                })

                total_memory_usage_mb += host_memory_usage_mb
                total_memory_capacity_mb += host_memory_capacity_mb
                total_cpu_usage_mhz += host_cpu_usage_mhz
                total_cpu_capacity_mhz += host_cpu_capacity_mhz

            total_memory_usage_gb = total_memory_usage_mb / 1024  # Convert MB to GB
            total_memory_capacity_gb = total_memory_capacity_mb / 1024  # Convert MB to GB
            total_cpu_usage_ghz = total_cpu_usage_mhz / 1000  # Convert MHz to GHz
            total_cpu_capacity_ghz = total_cpu_capacity_mhz / 1000  # Convert MHz to GHz

            memory_load_percentage = (total_memory_usage_gb / total_memory_capacity_gb) * 100
            cpu_load_percentage = (total_cpu_usage_ghz / total_cpu_capacity_ghz) * 100

            return {
                "vcenter_fqdn": service_instance._stub.host,  # vCenter FQDN
                "vcenter_name": service_instance.content.about.name,  # vCenter name
                "cluster_name": cluster.name,  # Cluster name
                "hosts": host_data,
                "total_used_gb": total_memory_usage_gb,
                "total_capacity_gb": total_memory_capacity_gb,
                "total_free_gb": total_memory_capacity_gb - total_memory_usage_gb,
                "total_cpu_usage_ghz": total_cpu_usage_ghz,
                "total_cpu_capacity_ghz": total_cpu_capacity_ghz,
                "total_cpu_free_ghz": total_cpu_capacity_ghz - total_cpu_usage_ghz,
                "memory_load_percentage": memory_load_percentage,
                "cpu_load_percentage": cpu_load_percentage
            }
        else:
            print(f"Cluster '{cluster_name}' not found.")
            return {}
    except Exception as e:
        print(f"Error: {str(e)}")
        return {}

# Function to format desktop pools
def format_desktop_pool(pool):
    pool_id = pool.get('id', 'N/A')
    pool_name = pool.get('name', 'N/A')
    return pool_id, pool_name

# Function to count machines by state in pool
def count_machines_by_state_in_pool(session, server, pool_id):
    machines_url = f"{server}{machines_endpoint}"
    response = session.get(machines_url, verify=False)
    
    if response.status_code == 200:
        machines = response.json()
        state_counts = {state: 0 for state in states_to_count}
        
        for machine in machines:
            if machine.get('desktop_pool_id') == pool_id:
                state = machine.get('state')
                if state in state_counts:
                    state_counts[state] += 1
        
        return state_counts
    else:
        return {state: 0 for state in states_to_count}

# Function to fetch data from Horizon server
def fetch_data_from_horizon_server(server, auth_data):
    auth_url = f"{server}{auth_endpoint}"
    desktop_pools_url = f"{server}{desktop_pools_endpoint}"

    session = requests.Session()
    auth_response = session.post(auth_url, json=auth_data, verify=False)

    if auth_response.status_code == 200:
        token = auth_response.json().get('access_token')
        if token:
            session.headers.update({'Authorization': f'Bearer {token}'})
            
            response = session.get(desktop_pools_url, verify=False)
            
            if response.status_code == 200:
                desktop_pools = response.json()
                server_data = []
                
                for pool in desktop_pools:
                    pool_id, pool_name = format_desktop_pool(pool)
                    if "test" not in pool_name.lower():
                        state_counts = count_machines_by_state_in_pool(session, server, pool_id)
                        server_data.append({
                            "pool_name": pool_name,
                            "state_counts": state_counts
                        })
                
                return server_data
            else:
                return [{"error": f"Failed to fetch pools (Status: {response.status_code})"}]
        else:
            return [{"error": "Failed to get token"}]
    else:
        return [{"error": "Authentication failed"}]

    session.close()

# Function to fetch all data from Horizon servers
def fetch_all_horizon_server_data(auth_data):
    print("Fetching fresh data from Horizon servers...")
    all_server_data = {}
    for server in horizon_servers:
        all_server_data[server] = fetch_data_from_horizon_server(server, auth_data)
    return all_server_data, datetime.now()

# Function to fetch all data from vCenter servers using the same service instances
def fetch_all_vcenter_data(service_instance_1, service_instance_2):
    print("Fetching fresh data from vCenter servers...")
    all_vcenter_data = {}

    if service_instance_1 and service_instance_2:
        all_vcenter_data["vcenter1"] = get_cluster_performance_metrics(service_instance_1, vcenter_credentials["cluster_1"])
        all_vcenter_data["vcenter2"] = get_cluster_performance_metrics(service_instance_2, vcenter_credentials["cluster_2"])
    else:
        print("Error: One or both vCenter sessions are not available.")

    return all_vcenter_data, datetime.now()

class HTMLGenerator:
    def __init__(self, states_display_order):
        self.states_display_order = states_display_order

    def generate_content_html(self, all_horizon_server_data, all_vcenter_data):
        html = '<h2>Horizon Server Data</h2>'
        for server, server_data in all_horizon_server_data.items():
            html += f'''
            <div class="server">
                <div class="server-header">{server}</div>
            '''
            for pool in server_data:
                if "error" in pool:
                    html += f'<p class="error-message">{pool["error"]}</p>'
                else:
                    html += f'<div class="pool-name">{pool["pool_name"]}</div>'
                    html += '<div class="states-container">'
                    for state in self.states_display_order:
                        count = pool["state_counts"].get(state, 0)
                        class_name = "state-gt-0" if count > 0 else "state-0"
                        html += f'''
                        <div class="state-wrapper">
                            <span class="state-label">{state}</span>
                            <span class="state-value {class_name}">{count}</span>
                        </div>
                        '''
                    html += '</div>'
            html += '</div>'

        # vCenter Server Data Generation
        html += '<h2>vCenter Server Data</h2>'
        if all_vcenter_data:
            for vcenter_id, vcenter_data in all_vcenter_data.items():
                memoryLoadPercentage = vcenter_data['memory_load_percentage']
                cpuLoadPercentage = vcenter_data['cpu_load_percentage']
                tableId = f"host-table-{vcenter_id}"
                html += f'''
                <div class="server vcenter-server">
                    <div class="vcenter-info">
                        <div class="server-header">
                            vCenter: {vcenter_data["vcenter_fqdn"]} - Cluster: {vcenter_data["cluster_name"]}
                            <button class="toggle-btn" onclick="toggleTable('{tableId}')">Expand</button>
                        </div>
                        <p><strong>Memory Usage:</strong> {vcenter_data["total_used_gb"]:.2f} GB / {vcenter_data["total_capacity_gb"]:.2f} GB ({memoryLoadPercentage:.2f}%)</p>
                        <div class="progress-bar-container">
                            <div class="progress-bar" style="width:{memoryLoadPercentage:.2f}%; background-color:{self.get_bar_color(memoryLoadPercentage)};"></div>
                        </div>
                        <p><strong>CPU Usage:</strong> {vcenter_data["total_cpu_usage_ghz"]:.2f} GHz / {vcenter_data["total_cpu_capacity_ghz"]:.2f} GHz ({cpuLoadPercentage:.2f}%)</p>
                        <div class="progress-bar-container">
                            <div class="progress-bar" style="width:{cpuLoadPercentage:.2f}%; background-color:{self.get_bar_color(cpuLoadPercentage)};"></div>
                        </div>
                    </div>
                    <div class="host-table-container" id="{tableId}" style="display: none;">
                        <table class="compact-table">
                            <thead>
                                <tr>
                                    <th>Host</th>
                                    <th>Used Memory (GB)</th>
                                    <th>Total Memory (GB)</th>
                                    <th>Free Memory (GB)</th>
                                    <th>CPU Usage (GHz)</th>
                                    <th>Total CPU (GHz)</th>
                                    <th>Free CPU (GHz)</th>
                                </tr>
                            </thead>
                            <tbody>
                '''
                for host in vcenter_data["hosts"]:
                    html += f'''
                    <tr>
                        <td>{host["name"]}</td>
                        <td>{host["used_memory_gb"]:.2f} GB</td>
                        <td>{host["total_memory_gb"]:.2f} GB</td>
                        <td>{host["free_memory_gb"]:.2f} GB</td>
                        <td>{host["cpu_usage_ghz"]:.2f} GHz</td>
                        <td>{host["cpu_capacity_ghz"]:.2f} GHz</td>
                        <td>{host["cpu_free_ghz"]:.2f} GHz</td>
                    </tr>
                    '''
                html += '''
                            </tbody>
                        </table>
                    </div>
                </div>
                '''
        else:
            html += '<p>No vCenter data available.</p>'

        return html

    def get_bar_color(self, percentage):
        if percentage < 50:
            return '#4caf50'  # Green
        elif percentage < 80:
            return '#ffeb3b'  # Yellow
        else:
            return '#f44336'  # Red

    def generate_dashboard_html(self, all_horizon_server_data, all_vcenter_data, fetch_time):
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Combined VMware Horizon and vCenter Dashboard</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #f0f0f0;
                    margin: 0;
                    padding: 20px;
                    color: #333;
                }}
                h1 {{
                    text-align: center;
                    font-size: 24px;
                    margin-bottom: 20px;
                    color: #444;
                }}
                .server {{
                    background-color: #fff;
                    border-radius: 8px;
                    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
                    padding: 10px;
                    margin-bottom: 15px;
                    width: 100%;
                }}
                .vcenter-server {{
                    display: flex;
                    justify-content: space-between;
                }}
                .vcenter-info {{
                    width: 45%;
                }}
                .host-table-container {{
                    width: 50%;
                    display: none;  /* Initially hide the host table */
                }}
                .server-header {{
                    background-color: #f5f5f5;
                    padding: 8px;
                    font-weight: bold;
                    font-size: 14px;
                    border-radius: 6px 6px 0 0;
                    border-bottom: 1px solid #ddd;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }}
                .toggle-btn {{
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 5px 10px;
                    cursor: pointer;
                }}
                .pool-name {{
                    font-size: 16px;
                    font-weight: bold;
                    margin: 10px 0;
                    color: #333;
                }}
                .states-container {{
                    display: flex;
                    flex-wrap: wrap;
                    margin-top: 8px;
                    gap: 10px;
                }}
                .state-wrapper {{
                    display: flex;
                    align-items: center;
                    background-color: #f9f9f9;
                    padding: 5px 10px;
                    border-radius: 5px;
                    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
                }}
                .state-label {{
                    font-size: 12px;
                    font-weight: bold;
                    color: #555;
                    margin-right: 5px;
                }}
                .state-value {{
                    font-size: 14px;
                    font-weight: bold;
                    padding: 4px 8px;
                    border-radius: 4px;
                }}
                .state-0 {{
                    background-color: #ffcccc;
                    color: #800000;
                }}
                .state-gt-0 {{
                    background-color: #ccffcc;
                    color: #006600;
                }}
                .error-message {{
                    color: #ff0000;
                    font-weight: bold;
                    margin-left: 10px;
                }}
                #controls {{
                    text-align: right;
                    margin-bottom: 20px;
                    font-size: 14px;
                    color: #555;
                }}
                #controls select {{
                    padding: 5px;
                    border-radius: 4px;
                    border: 1px solid #ddd;
                }}
                .progress-bar-container {{
                    width: 100%;
                    background-color: #e0e0e0;
                    border-radius: 4px;
                    overflow: hidden;
                    margin: 3px 0;
                }}
                .progress-bar {{
                    height: 15px;
                    background-color: #4caf50; /* Green by default */
                    width: 0; /* This will be set dynamically */
                    border-radius: 4px;
                }}
                .compact-table {{
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 12px;
                    margin-top: 10px;
                }}
                .compact-table, th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #f5f5f5;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <div>
                <h1>Combined VMware Horizon and vCenter Dashboard</h1>
                <div id="controls">
                    Auto-refresh: 
                    <select id="refreshInterval" onchange="updateRefreshInterval()">
                        <option value="0">Off</option>
                        <option value="30">30 seconds</option>
                        <option value="60" selected>1 minute</option>
                        <option value="300">5 minutes</option>
                    </select>
                </div>
                <p>Page loaded at: <span id="loadTime">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span></p>
                <p>Data fetched at: <span id="fetchTime">{fetch_time.strftime('%Y-%m-%d %H:%M:%S')}</span></p>
                <div id="content">
                    {self.generate_content_html(all_horizon_server_data, all_vcenter_data)}
                </div>
            </div>
            <script>
                let refreshIntervalId;
                const statesDisplayOrder = {json.dumps(self.states_display_order)};

                function updateRefreshInterval() {{
                    clearInterval(refreshIntervalId);
                    const interval = document.getElementById('refreshInterval').value;
                    if (interval > 0) {{
                        refreshIntervalId = setInterval(refreshData, interval * 1000);
                    }}
                }}

                function refreshData() {{
                    fetch('/get_data')
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('content').innerHTML = generateContentHtml(data.server_data, data.vcenter_data);
                            document.getElementById('fetchTime').textContent = data.fetch_time;
                        }})
                        .catch(error => console.error('Error:', error));
                }}

                function generateContentHtml(serverData, vcenterData) {{
                    let html = '<h2>Horizon Server Data</h2>';
                    for (const [server, pools] of Object.entries(serverData)) {{
                        html += `<div class="server"><div class="server-header">${{server}}</div>`;
                        for (const pool of pools) {{
                            if (pool.error) {{
                                html += `<p class="error-message">${{pool.error}}</p>`;
                            }} else {{
                                html += `<div class="pool-name">${{pool.pool_name}}</div>`;
                                html += '<div class="states-container">';
                                for (const state of statesDisplayOrder) {{
                                    const count = pool.state_counts[state] || 0;
                                    const className = count > 0 ? "state-gt-0" : "state-0";
                                    html += `
                                    <div class="state-wrapper">
                                        <span class="state-label">${{state}}</span>
                                        <span class="state-value ${{className}}">${{count}}</span>
                                    </div>`;
                                }}
                                html += '</div>';
                            }}
                        }}
                        html += '</div>';
                    }}
                    html += '<h2>vCenter Server Data</h2>';
                    for (const [vcenter_id, vcenter_data] of Object.entries(vcenterData)) {{
                        const memoryLoadPercentage = vcenter_data.memory_load_percentage.toFixed(2);
                        const cpuLoadPercentage = vcenter_data.cpu_load_percentage.toFixed(2);
                        const tableId = `host-table-${{vcenter_id}}`;
                        html += `<div class="server vcenter-server">`;
                        html += `<div class="vcenter-info"><div class="server-header">vCenter: ${{vcenter_data.vcenter_fqdn}} - Cluster: ${{vcenter_data.cluster_name}} <button class="toggle-btn" onclick="toggleTable('${{tableId}}')">Expand</button></div>`;
                        html += `<p><strong>Memory Usage:</strong> ${{vcenter_data.total_used_gb.toFixed(2)}} GB / ${{vcenter_data.total_capacity_gb.toFixed(2)}} GB (${{memoryLoadPercentage}}%)</p>`;
                        html += `<div class="progress-bar-container"><div class="progress-bar" style="width:${{memoryLoadPercentage}}%; background-color:${{getBarColor(parseFloat(memoryLoadPercentage))}};"></div></div>`;
                        html += `<p><strong>CPU Usage:</strong> ${{vcenter_data.total_cpu_usage_ghz.toFixed(2)}} GHz / ${{vcenter_data.total_cpu_capacity_ghz.toFixed(2)}} GHz (${{cpuLoadPercentage}}%)</p>`;
                        html += `<div class="progress-bar-container"><div class="progress-bar" style="width:${{cpuLoadPercentage}}%; background-color:${{getBarColor(parseFloat(cpuLoadPercentage))}};"></div></div></div>`;
                        html += `<div class="host-table-container" id="${{tableId}}"><table class="compact-table"><thead><tr><th>Host</th><th>Used Memory (GB)</th><th>Total Memory (GB)</th><th>Free Memory (GB)</th><th>CPU Usage (GHz)</th><th>Total CPU (GHz)</th><th>Free CPU (GHz)</th></tr></thead><tbody>`;
                        for (const host of vcenter_data.hosts) {{
                            html += `<tr><td>${{host.name}}</td><td>${{host.used_memory_gb.toFixed(2)}} GB</td><td>${{host.total_memory_gb.toFixed(2)}} GB</td><td>${{host.free_memory_gb.toFixed(2)}} GB</td><td>${{host.cpu_usage_ghz.toFixed(2)}} GHz</td><td>${{host.cpu_capacity_ghz.toFixed(2)}} GHz</td><td>${{host.cpu_free_ghz.toFixed(2)}} GHz</td></tr>`;
                        }}
                        html += '</tbody></table></div></div>';
                    }}
                    return html;
                }}

                function toggleTable(tableId) {{
                    const tableContainer = document.getElementById(tableId);
                    const toggleBtn = tableContainer.previousElementSibling.querySelector('.toggle-btn');
                    if (tableContainer.style.display === "none" || tableContainer.style.display === "") {{
                        tableContainer.style.display = "block";
                        toggleBtn.textContent = "Collapse";
                    }} else {{
                        tableContainer.style.display = "none";
                        toggleBtn.textContent = "Expand";
                    }}
                }}

                function getBarColor(percentage) {{
                    if (percentage < 50) {{
                        return '#4caf50';  // Green
                    }} else if (percentage < 80) {{
                        return '#ffeb3b';  // Yellow
                    }} else {{
                        return '#f44336';  // Red
                    }}
                }}

                document.addEventListener("DOMContentLoaded", function() {{
                    updateRefreshInterval();
                }});
            </script>
        </body>
        </html>
        """
        return html

    def generate_login_html(self, error=None):
        error_message = f'<p style="color: red;">{error}</p>' if error else ''
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Login - Combined VMware Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
                form {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
                input {{ margin: 10px 0; padding: 5px; width: 200px; }}
                input[type="submit"] {{ width: auto; cursor: pointer; }}
            </style>
        </head>
        <body>
            <form action="/login" method="post">
                <h2>Login to Combined VMware Dashboard</h2>
                {error_message}
                <input type="text" name="domain" placeholder="Domain" required><br>
                <input type="text" name="username" placeholder="Username" required><br>
                <input type="password" name="password" placeholder="Password" required><br>
                <input type="submit" value="Login">
            </form>
        </body>
        </html>
        """



class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        html_gen = HTMLGenerator(states_display_order)
        if self.path == '/':
            # Check if the user is logged in
            session_id = self.get_session_id()
            if session_id in sessions:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                auth_data = sessions[session_id]["auth_data"]
                service_instance_1 = sessions[session_id]["service_instance_1"]
                service_instance_2 = sessions[session_id]["service_instance_2"]
                all_horizon_server_data, _ = fetch_all_horizon_server_data(auth_data)
                all_vcenter_data, _ = fetch_all_vcenter_data(service_instance_1, service_instance_2)
                html_content = html_gen.generate_dashboard_html(all_horizon_server_data, all_vcenter_data, datetime.now())
                self.wfile.write(html_content.encode())
            else:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                html_content = html_gen.generate_login_html()
                self.wfile.write(html_content.encode())
        elif self.path == '/get_data':
            session_id = self.get_session_id()
            if session_id in sessions:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                auth_data = sessions[session_id]["auth_data"]
                service_instance_1 = sessions[session_id]["service_instance_1"]
                service_instance_2 = sessions[session_id]["service_instance_2"]
                all_horizon_server_data, _ = fetch_all_horizon_server_data(auth_data)
                all_vcenter_data, _ = fetch_all_vcenter_data(service_instance_1, service_instance_2)
                response_data = {
                    'server_data': all_horizon_server_data,
                    'vcenter_data': all_vcenter_data,
                    'fetch_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                self.wfile.write(json.dumps(response_data).encode())
            else:
                self.send_error(401, "Unauthorized")
        else:
            self.send_error(404)

    def do_POST(self):
        html_gen = HTMLGenerator(states_display_order)
        if self.path == '/login':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            
            # Extracting credentials from the login form
            domain = params.get('domain', [''])[0]
            username = params.get('username', [''])[0]
            password = params.get('password', [''])[0]

            # Combine domain and username for vCenter login if domain is provided
            vcenter_username = f"{domain}\\{username}" if domain else username

            # Prepare auth_data for Horizon login
            auth_data = {
                "domain": domain,
                "username": username,
                "password": password
            }

            # Test Horizon credentials (as before)
            test_server = horizon_servers[0]
            test_result = fetch_data_from_horizon_server(test_server, auth_data)

            # Minimal vCenter connection test
            print("Testing vCenter login credentials...")
            print(f"vCenter Host: {vcenter_credentials['host_1']}")


            service_instance_1 = connect_to_vcenter(vcenter_credentials["host_1"], vcenter_username, password)
            service_instance_2 = connect_to_vcenter(vcenter_credentials["host_2"], vcenter_username, password)

            if service_instance_1:
                print("Successfully connected to vCenter 1")
            if service_instance_2:
                print("Successfully connected to vCenter 2")

            # Check if both Horizon and vCenter logins are successful
            if not any("error" in item for item in test_result) and service_instance_1 and service_instance_2:
                # Store the service instances in the session data
                session_id = str(uuid.uuid4())
                sessions[session_id] = {
                    "auth_data": auth_data,
                    "service_instance_1": service_instance_1,
                    "service_instance_2": service_instance_2
                }
                self.send_response(302)
                self.send_header('Location', '/')
                self.send_header('Set-Cookie', f'session_id={session_id}; HttpOnly; Path=/')
                self.end_headers()
            else:
                # Invalid credentials or login failure for either Horizon or vCenter
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                error_message = "Invalid credentials. Please try again."
                if not service_instance_1 or not service_instance_2:
                    error_message += " (vCenter login failed)"
                if any("error" in item for item in test_result):
                    error_message += " (Horizon login failed)"
                html_content = html_gen.generate_login_html(error_message)
                self.wfile.write(html_content.encode())

    def get_session_id(self):
        cookies = self.headers.get('Cookie')
        if cookies:
            for cookie in cookies.split(';'):
                name, value = cookie.strip().split('=', 1)
                if name == 'session_id':
                    return value
        return None

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "localhost"

def run_server(port=2834):
    server_address = ('0.0.0.0', port)  # Bind to all interfaces
    httpd = HTTPServer(server_address, RequestHandler)
    local_ip = get_local_ip()
    print(f"Server running on:")
    print(f"http://{local_ip}:{port}")
    print(f"http://localhost:{port}")
    print(f"http://127.0.0.1:{port}")
    print("Click on any of the above links to open the page.")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()

