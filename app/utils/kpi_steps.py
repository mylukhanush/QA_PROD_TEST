"""
Predefined steps and configurations for the Performance KPI Report.
"""

KPI_STEPS = [
    # ── 1. Login Page ──────────────────────────────────────────────────────────
    {
        "category": "Login Page",
        "parameter": "OTP Generation",
        "url_suffix": "/#/auth/login",
        "type": "login_otp"
    },
    {
        "category": "Login Page",
        "parameter": "Login Status",
        "url_suffix": "/#/auth/login",
        "type": "login_status"
    },

    # ── 2. Monitor > Command Centre ─────────────────────────────────────────────
    {
        "category": "Monitor > Command Centre",
        "parameter": "View all the vehicle status in Map view Page",
        "url_suffix": "/#/pages/command-center/summary",
        "type": "cc_map"
    },
    {
        "category": "Monitor > Command Centre",
        "parameter": "View all the vehicle in List view Page",
        "url_suffix": "/#/pages/command-center/summary",
        "type": "cc_list"
    },

    # ── 3. Monitor > Summary ────────────────────────────────────────────────────
    {
        "category": "Monitor > Summary",
        "parameter": "Widget Loading",
        "url_suffix": "/#/pages/dashboard/aggregate-dashboard",
        "type": "dashboard_widgets"
    },

    # ── 4. Monitor -> Video - View ──────────────────────────────────────────────
    {
        "category": "Monitor -> Video - View",
        "parameter": "Video Alerts(View)",
        "url_suffix": "/#/pages/dashboard/video",
        "type": "video_tab",
        "tab_name": "Video Alerts"
    },
    {
        "category": "Monitor -> Video - View",
        "parameter": "Camers Status(View)",
        "url_suffix": "/#/pages/dashboard/video",
        "type": "video_tab",
        "tab_name": "Camera Status"
    },
    {
        "category": "Monitor -> Video - View",
        "parameter": "Video Requests(View)",
        "url_suffix": "/#/pages/dashboard/video",
        "type": "video_tab",
        "tab_name": "Video Requests"
    },

    # ── 5. Monitor > IgnitionTrips ──────────────────────────────────────────────
    {
        "category": "Monitor > IgnitionTrips",
        "parameter": "History (View)",
        "url_suffix": "/#/pages/truckbooking/ignition-trips",
        "type": "ignition_tab",
        "tab_name": "History"
    },
    {
        "category": "Monitor > IgnitionTrips",
        "parameter": "Logs (View)",
        "url_suffix": "/#/pages/truckbooking/ignition-trips",
        "type": "ignition_tab",
        "tab_name": "Logs"
    },

    # ── 6. Trips > Multipoint Cargo Trip ────────────────────────────────────────
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "View All Ongoing Trip",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Ongoing"
    },
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "View All Upcoming Trip",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Upcoming"
    },
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "View All Completed/Cancel Trip",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Completed"
    },
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "View Trip Summary Page",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Summary"
    },

    # ── 7. Reports- Alert (View report) ─────────────────────────────────────────
    {
        "category": "Reports- Alert (View report)",
        "parameter": "Alert-Geofence Entry Exit",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Geofence"
    },
    {
        "category": "Reports- Alert (View report)",
        "parameter": "Alert-Ignation Status",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Ignition"
    },
    {
        "category": "Reports- Alert (View report)",
        "parameter": "Alert-Over Speed",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Overspeed"
    },
    {
        "category": "Reports- Alert (View report)",
        "parameter": "Alert-Power Status",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Power"
    },

    # ── 8. Other Reports (View Report) ──────────────────────────────────────────
    {
        "category": "Other Reports (View Report)",
        "parameter": "Distance",
        "url_suffix": "/#/pages/reports-new/distance-report",
        "type": "report_other"
    },
    {
        "category": "Other Reports (View Report)",
        "parameter": "IGN Master",
        "url_suffix": "/#/pages/reports-new/master-report",
        "type": "report_other"
    },
    {
        "category": "Other Reports (View Report)",
        "parameter": "IGN Analytics",
        "url_suffix": "/#/pages/reports-new/ignition-analytics",
        "type": "report_other"
    },
    {
        "category": "Other Reports (View Report)",
        "parameter": "Geofence",
        "url_suffix": "/#/pages/reports-new/geofenceaggregatenew",
        "type": "report_other"
    },
    {
        "category": "Other Reports (View Report)",
        "parameter": "Over Speeding",
        "url_suffix": "/#/pages/reports-new/overspeed",
        "type": "report_other"
    },
    {
        "category": "Other Reports (View Report)",
        "parameter": "Vehicle",
        "url_suffix": "/#/pages/reports-new/vehiclestatus",
        "type": "report_other"
    },
    {
        "category": "Other Reports (View Report)",
        "parameter": "IGN Trips",
        "url_suffix": "/#/pages/reports-new/logs-report",
        "type": "report_other"
    }
]

KPI_DOWNLOAD_STEPS = [
    # ── 1. Monitor > Command Centre ─────────────────────────────────────────────
    {
        "category": "Mointor > Command Centre",
        "parameter": "Download List view Page vehicle Data",
        "url_suffix": "/#/pages/command-center/summary",
        "type": "cc_list"
    },

    # ── 2. Monitor -> Video - Download ──────────────────────────────────────────
    {
        "category": "Mointor -> Video - Download",
        "parameter": "Video Alerts(Downlaod)",
        "url_suffix": "/#/pages/dashboard/video",
        "type": "video_tab",
        "tab_name": "Video Alerts"
    },
    {
        "category": "Mointor -> Video - Download",
        "parameter": "Camers Status(Download)",
        "url_suffix": "/#/pages/dashboard/video",
        "type": "video_tab",
        "tab_name": "Camera Status"
    },

    # ── 3. Trips > Multipoint Cargo Trip ────────────────────────────────────────
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "Download All Ongoing Trips",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Ongoing"
    },
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "Download Upcoming Trips",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Upcoming"
    },
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "Download Completed/Canceled Trips",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Completed"
    },
    {
        "category": "Trips > Multipoint Cargo Trip",
        "parameter": "Download Trip Summary Page - PDF Report",
        "url_suffix": "/#/pages/truckbooking/cargo-trips-new",
        "type": "cargo_tab",
        "tab_name": "Summary"
    },

    # ── 4. Reports- Alerts(Generate report) ─────────────────────────────────────
    {
        "category": "Reports- Alerts(Generate report)",
        "parameter": "Alert- Geofence Entry Exit",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Geofence"
    },
    {
        "category": "Reports- Alerts(Generate report)",
        "parameter": "Alert- IGN",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Ignition"
    },
    {
        "category": "Reports- Alerts(Generate report)",
        "parameter": "Alert- Over Speed",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Overspeed"
    },
    {
        "category": "Reports- Alerts(Generate report)",
        "parameter": "Alert- Power Status",
        "url_suffix": "/#/pages/reports-new/alerts-summary",
        "type": "report_alert",
        "alert_filter": "Power"
    },

    # ── 5. Other Reports (Generate Report) ──────────────────────────────────────
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "Distance",
        "url_suffix": "/#/pages/reports-new/distance-report",
        "type": "report_other"
    },
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "IGN Master",
        "url_suffix": "/#/pages/reports-new/master-report",
        "type": "report_other"
    },
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "IGN Analytics",
        "url_suffix": "/#/pages/reports-new/ignition-analytics",
        "type": "report_other"
    },
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "Geofence",
        "url_suffix": "/#/pages/reports-new/geofenceaggregatenew",
        "type": "report_other"
    },
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "Over Speeding",
        "url_suffix": "/#/pages/reports-new/overspeed",
        "type": "report_other"
    },
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "Vehicle",
        "url_suffix": "/#/pages/reports-new/vehiclestatus",
        "type": "report_other"
    },
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "Vehicle History",
        "url_suffix": "/#/pages/reports-new/vehicle-history",
        "type": "report_other"
    },
    {
        "category": "Other Reports (Generate Report)",
        "parameter": "IGN Trips",
        "url_suffix": "/#/pages/reports-new/logs-report",
        "type": "report_other"
    }
]
