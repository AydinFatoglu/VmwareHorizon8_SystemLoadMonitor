# VMware Horizon and vCenter Monitoring Dashboard

This project provides a web-based dashboard to monitor VMware Horizon and vCenter environments. It connects to up to 2 Horizon pods and 2 different vCenter servers, retrieving and displaying key performance metrics such as desktop pool statuses, memory usage, and CPU load.

## Features

- Monitor up to 2 Horizon pods and 2 vCenter servers.
- Display Horizon desktop pool statuses and count VMs in various states.
- View memory and CPU usage metrics for vCenter clusters.
- Web-based dashboard with auto-refresh capabilities.
- Secure login and session management.

## Requirements

- Python 3.x
- Libraries: `pyVmomi`, `pyVim`, `requests`

## Installation

1. Clone the repository and navigate to the directory.
2. Install required packages using `pip install -r requirements.txt`.
3. Configure the Horizon and vCenter server details in the script.
4. Run the server with `python dashboard.py`.
5. Access the dashboard at `http://localhost:2834`.

## Usage

- Log in with your Horizon or vCenter credentials.
- View real-time Horizon and vCenter data on the dashboard.
- Set auto-refresh to update data periodically.

## Limitations

- Supports monitoring a maximum of 2 Horizon pods and 2 vCenters.

## License

MIT License
