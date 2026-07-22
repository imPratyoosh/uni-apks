import os
import re
import sys
import json

LOG_FILE = 'build.log'
TEMPLATE_FILE = 'README.template.md'
OUTPUT_FILE = 'README.md'
STATE_FILE = 'apps_state.json'  # Our memory bank

def clean_terminal_formatting(text):
    """Removes ANSI color codes and timestamps from the log lines."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    text = re.sub(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+', '', text)
    return text.strip()

# 1. Load previous memory if it exists
if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            apps_data = json.load(f)
    except json.JSONDecodeError:
        apps_data = {}
else:
    apps_data = {}

current_app = None
current_bundles = []
apps_updated_this_run = 0

# 2. Parse the log file line by line
try:
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            clean_line = clean_terminal_formatting(line)
            
            # Reset trackers for the next app when a build finishes
            if "[+] Built" in clean_line or "[+] Done" in clean_line:
                current_bundles = []
                current_app = None

            # Detect Patch Bundles
            elif "Getting '" in clean_line and "' from '" in clean_line:
                match = re.search(r"Getting '(.*?)' from '(.*?)'", clean_line)
                if match:
                    filename = match.group(1)
                    url = match.group(2)
                    
                    if "cli" not in filename.lower() and "jar" not in filename.lower():
                        # Smarter URL parsing for both GitHub and GitLab
                        repo = "Unknown/Repo"
                        if '/repos/' in url:  # GitHub API
                            m = re.search(r'/repos/([^/]+/[^/]+)', url)
                            if m: repo = m.group(1)
                        elif '/projects/' in url:  # GitLab API
                            m = re.search(r'/projects/([^/]+)', url)
                            # GitLab URL-encodes the slash as %2F, so we decode it back
                            if m: repo = m.group(1).replace('%2F', '/')
                        else:  # Standard Web URLs fallback
                            m = re.search(r'(?:github\.com|gitlab\.com)/([^/]+/[^/]+)', url)
                            if m: repo = m.group(1)
                            
                        # Extract version (e.g. patches-1.34.0.mpp -> 1.34.0)
                        v_match = re.search(r'([\d\.]+)', filename)
                        version = v_match.group(1) if v_match else filename.replace('.mpp', '').replace('patches-', '')
                        
                        if not any(b['repo'] == repo for b in current_bundles):
                            current_bundles.append({'repo': repo, 'version': version})

            # Catch app name early
            elif "[+] Package name of '" in clean_line:
                match = re.search(r"Package name of '(.*?)' is", clean_line)
                if match:
                    current_app = match.group(1)
                    if current_app not in apps_data:
                        apps_data[current_app] = {'version': "Unknown", 'bundles': current_bundles.copy(), 'applied': [], 'excluded': []}
                        apps_updated_this_run += 1
                        
            # Detect App Name & Exact App Version
            elif "[+] Choosing version '" in clean_line:
                match = re.search(r"Choosing version '(.*?)' for '(.*?)'", clean_line)
                if match:
                    current_app = match.group(2)
                    # Overwrite or initialize this app's data for the fresh build
                    apps_data[current_app] = {'version': match.group(1), 'bundles': current_bundles.copy(), 'applied': [], 'excluded': []}
                    apps_updated_this_run += 1
                            
            # Detect Applied Patches
            elif current_app and "INFO: Applied: " in clean_line:
                patch = clean_line.split("INFO: Applied: ")[1].strip()
                if patch not in apps_data[current_app]['applied']:
                    apps_data[current_app]['applied'].append(patch)
                    
            # Detect Manually Excluded Patches
            elif current_app and "INFO: Skipping disabled: " in clean_line:
                patch = clean_line.split("INFO: Skipping disabled: ")[1].strip()
                if not patch.endswith("(default)"):
                    if patch not in apps_data[current_app]['excluded']:
                        apps_data[current_app]['excluded'].append(patch)

except FileNotFoundError:
    print(f"Warning: {LOG_FILE} not found. Skipping log parsing.")

# 3. Save the updated memory bank back to disk
with open(STATE_FILE, 'w', encoding='utf-8') as f:
    json.dump(apps_data, f, indent=4)

print(f"Memory updated. {apps_updated_this_run} apps updated from current log.")

# 4. Format the parsed data into Markdown
apps_md = ""
# Sort alphabetically to keep the README consistent regardless of build order
for index, app_name in enumerate(sorted(apps_data.keys()), start=1):
    data = apps_data[app_name]
    applied = data['applied']
    excluded = data['excluded']
    bundles = data['bundles']
    
    repos_list = [b['repo'] for b in bundles]
    versions_list = [b['version'] for b in bundles]
    
    apps_md += f"<details>\n<summary><b>{index}. {app_name}</b></summary>\n\n"
    
    # Add Versions and Bundles
    apps_md += f"* **App Version:** `{data['version']}`\n"
    if repos_list:
        apps_md += f"* **Patch Bundles:** `{', '.join(repos_list)}`\n"
    if versions_list:
        apps_md += f"* **Patches Version:** `{', '.join(versions_list)}`\n"
        
    apps_md += "\n"
    
    # Add Applied Patches
    apps_md += f"* **Applied Patches ({len(applied)}):**\n"
    if applied:
        for patch in sorted(applied):
            apps_md += f"  * `{patch}`\n"
    else:
        apps_md += "  * `No patches detected.`\n"
        
    # Add Excluded Patches
    if excluded:
        apps_md += f"\n* **Excluded Patches ({len(excluded)}):**\n"
        for patch in sorted(excluded):
            apps_md += f"  * `{patch}`\n"
            
    apps_md += "</details>\n\n"

# 5. Inject into README template
try:
    with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
        template = f.read()
except FileNotFoundError:
    print(f"Error: {TEMPLATE_FILE} not found.")
    sys.exit(1)

final_readme = template.replace('{{APPS_LIST}}', apps_md.strip())

# 6. Save the final README
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(final_readme)

print("README.md successfully generated from memory!")
