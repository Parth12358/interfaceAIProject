"""Seeded fake data for the test banking sites.

Special member IDs drive the assignment's runtime conditions deterministically:
    11111 / 22222  normal, eligible members
    33333          restricted record -> permission denial (business outcome)
    44444          not eligible for a sub-account -> permission denial
    55555          account in arrears -> business outcome (ACCOUNT_IN_ARREARS)
    66666          compliance hold -> unknown screen (escalation)
    77777          transient slowness -> recoverable "please wait"
    99999          simulated backend outage -> hard failure
    00000          not found -> business outcome (MEMBER_NOT_FOUND)
Everything else that is not exactly five digits -> validation error.
"""
from __future__ import annotations

# --- behaviour thresholds (how the tenant resolves a member id) ---------------
SPECIAL = {
    "not_found": "00000",
    "restricted": "33333",
    "not_eligible": "44444",
    "arrears": "55555",
    "compliance": "66666",
    "slow": "77777",
    "outage": "99999",
}


def _members(rows):
    """rows: (id, name, savings, checking, status)."""
    return {mid: {"name": n, "savings": s, "checking": c, "status": st}
            for mid, n, s, c, st in rows}

TENANTS: dict[str, dict] = {
    "meridian": {
        "app_id": "vaultcore",
        "institution": "Meridian Trust",
        "product": "VaultCore",
        "tagline": "Core Banking Terminal",
        "frameset": True,
        "nav": [("NAVIGATION", None), ("Member Lookup", "search"), ("Accounts", "welcome"),
                ("Transactions", "welcome"), ("Administration", "welcome")],
        "theme": {
            "masthead": "#0b2545",
            "accent": "#13315c",
            "nav_bg": "#e4ebf4",
            "link": "#123a63",
            "ok": "#0a6b2f",
            "warn": "#8a6d00",
            "bad": "#a11313",
        },
        "members": {
            "11111": {"name": "Jordan Avery", "savings": "$18,204.77", "checking": "$2,915.40", "status": "Active"},
            "22222": {"name": "Priya Raman", "savings": "$7,540.10", "checking": "$1,203.88", "status": "Active"},
            "33333": {"name": "Casey Nolan", "savings": "$3,110.02", "checking": "$410.55", "status": "Restricted"},
            "44444": {"name": "Morgan Ellis", "savings": "$905.31", "checking": "$88.00", "status": "Active"},
            "55555": {"name": "Dana Whitfield", "savings": "$0.00", "checking": "$0.00", "status": "In Arrears"},
            "66666": {"name": "Reese Calder", "savings": "$12,000.00", "checking": "$1.00", "status": "Active"},
            "77777": {"name": "Samir Haddad", "savings": "$31,580.45", "checking": "$4,020.10", "status": "Active"},
            "88888": {"name": "Alexis Monroe", "savings": "$2,240.00", "checking": "$300.00", "status": "Active"},
        },
    },
    "summit": {
        "app_id": "vaultcore",
        "institution": "Summit Credit Union",
        "product": "VaultCore",
        "tagline": "Member Servicing System",
        "frameset": False,
        "nav": [("NAVIGATION", None), ("Accounts", "welcome"), ("Member Lookup", "search"),
                ("Statements", "welcome"), ("Transactions", "welcome"), ("Administration", "welcome")],
        "theme": {
            "masthead": "#3d2b1f",
            "accent": "#6b4f2a",
            "nav_bg": "#f1ebe1",
            "link": "#5a3d1f",
            "ok": "#2f6b2f",
            "warn": "#8a6d00",
            "bad": "#a11313",
        },
        "members": {
            "11111": {"name": "Robin Okafor", "savings": "$42,318.09", "checking": "$761.55", "status": "Active"},
            "22222": {"name": "Leila Fontaine", "savings": "$1,205.44", "checking": "$908.12", "status": "Active"},
            "33333": {"name": "Owen Baxter", "savings": "$6,700.00", "checking": "$0.00", "status": "Restricted"},
            "44444": {"name": "Harper Quinn", "savings": "$410.00", "checking": "$12.00", "status": "Active"},
            "55555": {"name": "Nadia Serrano", "savings": "$0.00", "checking": "$0.00", "status": "In Arrears"},
            "66666": {"name": "Theo Lindqvist", "savings": "$9,999.99", "checking": "$100.00", "status": "Active"},
            "77777": {"name": "Mei Zhang", "savings": "$64,000.00", "checking": "$2,000.00", "status": "Active"},
            "88888": {"name": "Rafael Ortiz", "savings": "$3,300.00", "checking": "$220.00", "status": "Active"},
        },
    },
    "novabank": {
        "app_id": "novabank",
        "institution": "NovaBank",
        "product": "NovaBank Servicing",
        "tagline": "Relationship Banking Platform",
        "frameset": False,
        "theme": {
            "masthead": "#101828",
            "accent": "#2563eb",
            "nav_bg": "#f2f4f7",
            "link": "#1d4ed8",
            "ok": "#047857",
            "warn": "#b45309",
            "bad": "#b91c1c",
        },
        "members": {
            "11111": {"name": "Jordan Avery", "savings": "$18,204.77", "checking": "$2,915.40", "status": "Active"},
            "22222": {"name": "Priya Raman", "savings": "$7,540.10", "checking": "$1,203.88", "status": "Active"},
            "33333": {"name": "Casey Nolan", "savings": "$3,110.02", "checking": "$410.55", "status": "Restricted"},
            "44444": {"name": "Morgan Ellis", "savings": "$905.31", "checking": "$88.00", "status": "Active"},
            "55555": {"name": "Dana Whitfield", "savings": "$0.00", "checking": "$0.00", "status": "In Arrears"},
            "66666": {"name": "Reese Calder", "savings": "$12,000.00", "checking": "$1.00", "status": "Active"},
            "77777": {"name": "Samir Haddad", "savings": "$31,580.45", "checking": "$4,020.10", "status": "Active"},
            "88888": {"name": "Alexis Monroe", "savings": "$2,240.00", "checking": "$300.00", "status": "Active"},
        },
        # sub-account product catalogue (NovaBank multi-field form)
        "products": {
            "Holiday Savings": {"min_deposit": 25},
            "High-Yield Savings": {"min_deposit": 500},
            "Money Market": {"min_deposit": 2500},
        },
    },
    # ---------------------------------------------------------------------
    # Five distinct banks rendered by the generic `bank` tenant builder.
    # Each varies vendor product, layout style, colour language and label
    # vocabulary, so the same runtime conditions are exercised on genuinely
    # different surfaces rather than reskins.
    # ---------------------------------------------------------------------
    "firstcoastal": {
        "generic": True,
        "app_id": "tellercore",
        "institution": "First Coastal Bank",
        "product": "TellerCore",
        "tagline": "Retail Servicing Platform",
        "style": "legacy",
        "frameset": True,
        "special_flow": "closure",
        "theme": {"masthead": "#0a3d3a", "accent": "#0f514d", "nav_bg": "#e3f0ee",
                  "link": "#0c5b56", "ok": "#0a6b2f", "warn": "#8a6d00", "bad": "#a11313"},
        "nav": [("NAVIGATION", None), ("Member Lookup", "search"), ("Accounts", "welcome"),
                ("Transfers", "welcome"), ("Administration", "welcome")],
        "labels": {"member": "Member Number", "button": "Retrieve",
                   "search_title": "Member Search", "detail_title": "Member Account",
                   "prompt": "Look up a member", "nav_name": "Member Lookup",
                   "name": "Member Name", "status": "Account Status",
                   "savings": "Savings Balance", "checking": "Checking Balance"},
        "members": _members([
            ("11111", "Tessa Whitcomb", "$22,410.08", "$3,118.55", "Active"),
            ("22222", "Ravi Chandrasekhar", "$5,905.66", "$744.10", "Active"),
            ("33333", "Noel Baptiste", "$1,050.00", "$0.00", "Restricted"),
            ("44444", "Simone Lefevre", "$640.21", "$90.00", "Active"),
            ("55555", "Gareth Doyle", "$0.00", "$0.00", "In Arrears"),
            ("66666", "Hana Kobayashi", "$14,720.00", "$220.00", "Active"),
            ("77777", "Marcus Adeyemi", "$51,003.77", "$6,540.12", "Active"),
            ("88888", "Elena Vasquez", "$2,980.44", "$410.00", "Active"),
        ]),
    },
    "pioneer": {
        "generic": True,
        "app_id": "accountview",
        "institution": "Pioneer Savings Bank",
        "product": "AccountView",
        "tagline": "Branch Teller Suite",
        "style": "dense",
        "frameset": False,
        "special_flow": "closure",
        "theme": {"masthead": "#5a1a1a", "accent": "#7a2626", "nav_bg": "#f3e9e9",
                  "link": "#7a2626", "ok": "#2f6b2f", "warn": "#8a6d00", "bad": "#a11313"},
        "nav": [("NAVIGATION", None), ("Account Lookup", "search"), ("Statements", "welcome"),
                ("Transactions", "welcome"), ("Admin", "welcome")],
        "labels": {"member": "Account Number", "button": "Search",
                   "search_title": "Account Inquiry", "detail_title": "Account Summary",
                   "prompt": "Find an account", "nav_name": "Account Lookup",
                   "name": "Account Holder", "status": "Account State",
                   "savings": "Savings Balance", "checking": "Checking Balance"},
        "members": _members([
            ("11111", "Beatrice Lindholm", "$9,340.12", "$1,002.44", "Active"),
            ("22222", "Curtis Nakamura", "$27,881.90", "$5,600.00", "Active"),
            ("33333", "Deborah Kaur", "$4,015.00", "$0.00", "Restricted"),
            ("44444", "Emil Petrov", "$880.77", "$45.00", "Active"),
            ("55555", "Fiona Gallagher", "$0.00", "$0.00", "In Arrears"),
            ("66666", "Gustav Berg", "$19,450.00", "$310.00", "Active"),
            ("77777", "Ingrid Solberg", "$73,204.55", "$12,010.00", "Active"),
            ("88888", "Jamal Osei", "$3,110.23", "$260.00", "Active"),
        ]),
    },
    "harbor": {
        "generic": True,
        "app_id": "harborgreen",
        "institution": "Harbor Federal Credit Union",
        "product": "HARBOR GREEN",
        "tagline": "Host Terminal Session",
        "style": "terminal",
        "frameset": False,
        "special_flow": "wire",
        "theme": {"masthead": "#000000", "accent": "#101010", "nav_bg": "#050505",
                  "link": "#ffb000", "ok": "#33ff66", "warn": "#ffcc00", "bad": "#ff5555"},
        "nav": [("F1=INQUIRY", None), ("F2=ACCOUNTS", "welcome"), ("F3=TRANSFER", "welcome")],
        "labels": {"member": "ACCT-NBR", "button": "ENTER",
                   "search_title": "ACCOUNT INQUIRY", "detail_title": "ACCOUNT MASTER",
                   "prompt": "ACCOUNT NUMBER", "nav_name": "ACCOUNT INQUIRY",
                   "name": "PRIMARY NAME", "status": "ACCT STATUS",
                   "savings": "SAVINGS BAL", "checking": "CHECKING BAL"},
        "members": _members([
            ("11111", "HOWARD FINCH", "$15,220.40", "$2,010.00", "ACTIVE"),
            ("22222", "LUCIA MARTINEZ", "$8,004.19", "$1,150.00", "ACTIVE"),
            ("33333", "OSCAR DELANEY", "$2,000.00", "$0.00", "RESTRICTED"),
            ("44444", "PENNY OYELARAN", "$500.00", "$50.00", "ACTIVE"),
            ("55555", "QUENTIN FROST", "$0.00", "$0.00", "IN ARREARS"),
            ("66666", "ROSA KOWALSKI", "$11,111.11", "$111.00", "ACTIVE"),
            ("77777", "SILAS THORNTON", "$44,500.00", "$9,000.00", "ACTIVE"),
            ("88888", "TAMARA VOSS", "$1,700.00", "$300.00", "ACTIVE"),
        ]),
    },
    "cascade": {
        "generic": True,
        "app_id": "cascadeone",
        "institution": "Cascade National Bank",
        "product": "CascadeOne",
        "tagline": "Digital Relationship Platform",
        "style": "modern",
        "frameset": False,
        "special_flow": None,
        "theme": {"masthead": "#111827", "accent": "#7c3aed", "nav_bg": "#f5f3ff",
                  "link": "#6d28d9", "ok": "#059669", "warn": "#b45309", "bad": "#dc2626"},
        "nav": [("NAVIGATION", None), ("Members", "search"), ("Accounts", "welcome"),
                ("Insights", "welcome")],
        "labels": {"member": "Member Number", "button": "Continue",
                   "search_title": "Member Lookup", "detail_title": "Member Overview",
                   "prompt": "Find a member", "nav_name": "Members",
                   "name": "Member Name", "status": "Relationship Status",
                   "savings": "Savings Balance", "checking": "Checking Balance"},
        "members": _members([
            ("11111", "Nadia Fontaine", "$30,115.55", "$4,400.90", "Active"),
            ("22222", "Omar Haddad", "$6,720.00", "$820.00", "Active"),
            ("33333", "Priscilla Okafor", "$1,200.00", "$0.00", "Restricted"),
            ("44444", "Quinn Alvarez", "$700.10", "$60.00", "Active"),
            ("55555", "Roland Devereux", "$0.00", "$0.00", "In Arrears"),
            ("66666", "Sasha Volkov", "$17,000.00", "$500.00", "Active"),
            ("77777", "Tobias Mbeki", "$95,320.00", "$14,000.00", "Active"),
            ("88888", "Uma Krishnan", "$2,015.75", "$120.00", "Active"),
        ]),
    },
    "unionsquare": {
        "generic": True,
        "app_id": "ledgerpro",
        "institution": "Union Square Bank",
        "product": "LedgerPro",
        "tagline": "Commercial Servicing",
        "style": "legacy",
        "frameset": False,
        "special_flow": "wire",
        "theme": {"masthead": "#1f2937", "accent": "#374151", "nav_bg": "#eceff3",
                  "link": "#1f3a5f", "ok": "#0a6b2f", "warn": "#8a6d00", "bad": "#a11313"},
        "nav": [("NAVIGATION", None), ("Member Inquiry", "search"), ("Ledgers", "welcome"),
                ("Wire Desk", "welcome"), ("Audit", "welcome")],
        "labels": {"member": "Member No.", "button": "Fetch",
                   "search_title": "Member Inquiry", "detail_title": "Member Ledger",
                   "prompt": "Retrieve a member", "nav_name": "Member Inquiry",
                   "name": "Member Name", "status": "Ledger Status",
                   "savings": "Savings Balance", "checking": "Checking Balance"},
        "members": _members([
            ("11111", "Vivian Castellano", "$58,900.00", "$7,710.25", "Active"),
            ("22222", "Wesley Amara", "$13,455.80", "$2,300.00", "Active"),
            ("33333", "Ximena Rojas", "$3,300.00", "$0.00", "Restricted"),
            ("44444", "Yusuf Demir", "$910.00", "$75.00", "Active"),
            ("55555", "Zara Lindqvist", "$0.00", "$0.00", "In Arrears"),
            ("66666", "Anders Holt", "$21,000.00", "$400.00", "Active"),
            ("77777", "Bianca Moretti", "$120,450.00", "$18,000.00", "Active"),
            ("88888", "Caleb Nkosi", "$4,220.60", "$500.00", "Active"),
        ]),
    },
}


def tenant(name: str) -> dict:
    return TENANTS[name]


def resolve(tenant_name: str, member_id: str, skip_slow: bool = False) -> dict:
    """Classify a requested member id into a behaviour for the tenant."""
    t = TENANTS[tenant_name]
    mid = (member_id or "").strip()
    if not (len(mid) == 5 and mid.isdigit()):
        return {"kind": "validation", "member_id": mid}
    if mid == SPECIAL["outage"]:
        return {"kind": "outage", "member_id": mid}
    if mid == SPECIAL["slow"] and not skip_slow:
        return {"kind": "slow", "member_id": mid}
    if mid == SPECIAL["compliance"]:
        return {"kind": "compliance", "member_id": mid}
    member = t["members"].get(mid)
    if member is None:
        return {"kind": "not_found", "member_id": mid}
    status = str(member["status"]).lower()
    if status == "restricted":
        return {"kind": "restricted", "member_id": mid, "member": member}
    if status == "in arrears":
        return {"kind": "arrears", "member_id": mid, "member": member}
    return {"kind": "ok", "member_id": mid, "member": member}
