import customtkinter as ctk
from customtkinter import CTkLabel, CTkButton, CTkFrame, CTkScrollableFrame, set_appearance_mode, set_default_color_theme
import json
import os
import undetected_chromedriver as uc
import threading
import re  # For sanitizing filenames
import pathlib  # For easier path handling
import logging  # For better error reporting
import uuid  # For generating random usernames
import time  # For delays and timestamps
import tkinter as tk
from tkinter import messagebox

# --- Configuration Constants ---
WINDOW_WIDTH = 400
WINDOW_HEIGHT = 550
BG_COLOR = "#181818"
FRAME_COLOR = "#242424"
TEXT_COLOR = "#F0F0F0"
SECONDARY_TEXT_COLOR = "#AAAAAA"
PRIMARY_COLOR = "#2A9DF4"
PRIMARY_HOVER_COLOR = "#1C7CD6"
DELETE_COLOR = "#FF3B30"
DELETE_HOVER_COLOR = "#C70039"

# --- Status Colors ---
STATUS_IDLE_COLOR = TEXT_COLOR  # Normal text color when idle
STATUS_LOADING_COLOR = "#FFA500"  # Orange/Yellow for loading
STATUS_RUNNING_COLOR = "#00FF7F"  # Green for running

ACCOUNT_ITEM_HEIGHT = 50
ACCOUNT_ITEM_PADX = 10
ACCOUNT_ITEM_PADY = 5
SELECTED_BORDER_COLOR = PRIMARY_COLOR
SELECTED_BORDER_WIDTH = 2

FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_SUBTITLE = ("Segoe UI", 14)
FONT_STATUS = ("Segoe UI", 10, "italic")
FONT_BUTTON = ("Segoe UI", 14, "bold")
FONT_MESSAGE = ("Segoe UI", 18)
FONT_ICON = ("Segoe UI Emoji", 18)

ACCOUNTS_FILE = "accounts.json"
PROFILES_BASE_DIR_NAME = "chrome_profiles"  # Subdirectory for profiles

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
)

# --- Helper Functions ---

def sanitize_filename(name):
    """Removes or replaces characters invalid for directory names."""
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    if not sanitized:
        return f"profile_{uuid.uuid4().hex[:8]}"
    return sanitized

def load_accounts(profiles_base_path):
    """Loads accounts, ensures profile directories exist, returns accounts and initial states."""
    accounts = []
    initial_states = {}
    needs_resave = False
    if not os.path.exists(ACCOUNTS_FILE):
        logging.info(f"{ACCOUNTS_FILE} not found. Starting fresh.")
        return [], {}
    try:
        with open(ACCOUNTS_FILE, 'r') as f:
            data = json.load(f)
        if isinstance(data, list):
            for acc in data:
                if isinstance(acc, dict) and 'username' in acc and 'profile_dir_name' in acc:
                    profile_dir_name = acc['profile_dir_name']
                    if not profile_dir_name:
                        logging.warning(f"Account '{acc['username']}' has empty profile_dir_name. Generating.")
                        acc['profile_dir_name'] = sanitize_filename(acc['username'])
                        profile_dir_name = acc['profile_dir_name']
                        needs_resave = True
                    profile_path = profiles_base_path / profile_dir_name
                    try:
                        profile_path.mkdir(parents=True, exist_ok=True)
                        logging.debug(f"Ensured profile directory exists: {profile_path}")
                    except OSError as e:
                        logging.error(f"Failed to create profile directory {profile_path}: {e}")
                    accounts.append(acc)
                    initial_states[profile_dir_name] = 'idle'
                elif isinstance(acc, dict) and 'username' in acc:
                    logging.warning(f"Account '{acc['username']}' missing profile_dir_name. Generating.")
                    acc['profile_dir_name'] = sanitize_filename(acc['username'])
                    profile_dir_name = acc['profile_dir_name']
                    temp_names = {a.get('profile_dir_name') for a in accounts} | set(initial_states.keys())
                    count = 1
                    original_name = profile_dir_name
                    while profile_dir_name in temp_names:
                        profile_dir_name = f"{original_name}_{count}"
                        count += 1
                    acc['profile_dir_name'] = profile_dir_name
                    profile_path = profiles_base_path / profile_dir_name
                    try:
                        profile_path.mkdir(parents=True, exist_ok=True)
                    except OSError as e:
                        logging.error(f"Failed to create profile directory {profile_path} for legacy account: {e}")
                    accounts.append(acc)
                    initial_states[profile_dir_name] = 'idle'
                    needs_resave = True
                else:
                    logging.warning(f"Skipping invalid account entry: {acc}")

            if needs_resave:
                logging.info("Profile directory names were generated/fixed. Saving changes.")
                save_accounts(accounts)
        else:
            logging.warning(f"{ACCOUNTS_FILE} does not contain a valid list. Starting fresh.")
            return [], {}
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Error loading {ACCOUNTS_FILE}: {e}. Starting with empty list.")
        return [], {}
    logging.info(f"Loaded {len(accounts)} accounts.")
    return accounts, initial_states

def save_accounts(accounts):
    """Saves accounts to the JSON file."""
    try:
        accounts_to_save = [{k: v for k, v in acc.items() if k in ['username', 'profile_dir_name']} for acc in accounts]
        with open(ACCOUNTS_FILE, 'w') as f:
            json.dump(accounts_to_save, f, indent=4)
        logging.debug(f"Accounts saved to {ACCOUNTS_FILE}")
    except IOError as e:
        logging.error(f"Error saving accounts to {ACCOUNTS_FILE}: {e}")

# --- Main Application Class ---
class AccountSwitcher(ctk.CTk):
    def __init__(self):
        super().__init__()

        set_appearance_mode("dark")  # Use dark appearance
        set_default_color_theme("blue")  # Optional: use built-in theme

        self.title("Account Manager")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.configure(fg_color=BG_COLOR)
        self.resizable(False, False)

        # --- Setup Profile Directory ---
        script_dir = pathlib.Path(__file__).parent.resolve()
        self.profiles_base_dir = script_dir / PROFILES_BASE_DIR_NAME
        try:
            self.profiles_base_dir.mkdir(parents=True, exist_ok=True)
            logging.info(f"Using profile base directory: {self.profiles_base_dir}")
        except OSError as e:
            logging.critical(f"Could not create base profile directory {self.profiles_base_dir}: {e}")
            self.display_critical_error(f"Failed to create profile directory:\n{self.profiles_base_dir}\nError: {e}\n\nThe application cannot continue.")
            self.after(100, self.quit)
            return

        self.accounts, self.profile_states = load_accounts(self.profiles_base_dir)
        self.status_labels = {}  # References for status labels {profile_dir_name: CTkLabel}
        self.current_account_index = 0 if self.accounts else -1

        # Dictionary to track last launch timestamps for profiles that have been opened
        self.profile_last_launch = {}

        # --- GUI Elements ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        self.title_label = ctk.CTkLabel(self.main_frame, text="ChatGPT Accounts", font=FONT_TITLE, text_color=TEXT_COLOR)
        self.title_label.pack(pady=(0, 10))

        self.no_accounts_label = ctk.CTkLabel(
            self.main_frame,
            text="No accounts found.\nAdd one to get started!",
            font=FONT_MESSAGE,
            text_color=SECONDARY_TEXT_COLOR,
            wraplength=WINDOW_WIDTH - 80
        )

        self.account_list_frame = CTkScrollableFrame(
            self.main_frame,
            fg_color="transparent",
            scrollbar_fg_color=FRAME_COLOR,
            scrollbar_button_color=SECONDARY_TEXT_COLOR,
            scrollbar_button_hover_color=FRAME_COLOR
        )
        # Packing handled in update_account_list_display

        # --- Button Frame with Switch and Add Buttons ---
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.button_frame.pack(side="bottom", fill="x", pady=(10, 0))
        self.button_frame.columnconfigure(0, weight=1)
        self.button_frame.columnconfigure(1, weight=1)

        self.switch_button = ctk.CTkButton(
            self.button_frame,
            text="⟲ Switch",
            command=self.switch_account,
            width=150,
            height=40,
            corner_radius=20,
            fg_color=PRIMARY_COLOR,
            hover_color=PRIMARY_HOVER_COLOR,
            text_color=TEXT_COLOR,
            font=FONT_BUTTON
        )
        self.switch_button.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        self.add_button = ctk.CTkButton(
            self.button_frame,
            text="✚ Add",
            command=self.add_random_account,
            width=150,
            height=40,
            corner_radius=20,
            fg_color=PRIMARY_COLOR,
            hover_color=PRIMARY_HOVER_COLOR,
            text_color=TEXT_COLOR,
            font=FONT_BUTTON
        )
        self.add_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.update_account_list_display()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def display_critical_error(self, message):
        """Shows a critical error message using tkinter messagebox."""
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Critical Error", message)
            root.destroy()
        except Exception as e:
            logging.error(f"Failed to display critical error message box: {e}")

    def _update_status_label(self, profile_dir_name, status_text, status_color):
        """Safely updates the status label for a given profile on the main thread."""
        if profile_dir_name in self.status_labels:
            status_label = self.status_labels[profile_dir_name]
            try:
                if status_label.winfo_exists():
                    status_label.configure(text=status_text, text_color=status_color)
                else:
                    logging.warning(f"Status label for {profile_dir_name} no longer exists.")
                    if profile_dir_name in self.status_labels:
                        del self.status_labels[profile_dir_name]
            except Exception as e:
                logging.error(f"Error configuring status label for {profile_dir_name}: {e}")
        else:
            logging.warning(f"No status label found for {profile_dir_name} during update.")

    def _set_profile_state(self, profile_dir_name, state):
        """Updates the state dictionary and corresponding GUI label for a profile."""
        self.profile_states[profile_dir_name] = state
        logging.info(f"Set state for '{profile_dir_name}' to '{state}'")

        # Choose a status text and icon (spinner for loading, checkmark for running)
        status_text = ""
        status_color = STATUS_IDLE_COLOR
        if state == 'loading':
            status_text = "⏳ Loading"
            status_color = STATUS_LOADING_COLOR
        elif state == 'running':
            status_text = "✓ Running"
            status_color = STATUS_RUNNING_COLOR
        elif state == 'idle':
            status_text = ""
            status_color = TEXT_COLOR

        self.after(0, self._update_status_label, profile_dir_name, status_text, status_color)

    def update_account_list_display(self):
        """Clears and redraws the account list in the scrollable frame."""
        for widget in self.account_list_frame.winfo_children():
            widget.destroy()
        self.status_labels.clear()

        if not self.accounts:
            self.account_list_frame.pack_forget()
            self.no_accounts_label.pack(pady=50, expand=True)
            logging.debug("Account list empty, showing 'no accounts' label.")
        else:
            self.no_accounts_label.pack_forget()
            self.account_list_frame.pack(pady=10, padx=0, fill="both", expand=True)
            logging.debug(f"Updating account list display with {len(self.accounts)} accounts.")
            for index, account in enumerate(self.accounts):
                if 'profile_dir_name' in account:
                    self.create_account_item(self.account_list_frame, account, index)
                else:
                    logging.error(f"Account at index {index} missing profile_dir_name. Skipping.")

    def create_account_item(self, parent_frame, account_data, index):
        """Creates a single account item widget including the status label."""
        profile_dir_name = account_data.get("profile_dir_name")
        if not profile_dir_name:
            logging.error(f"Cannot create item for index {index}: Missing profile_dir_name.")
            return

        current_state = self.profile_states.get(profile_dir_name, 'idle')
        is_selected = (index == self.current_account_index)
        border_width = SELECTED_BORDER_WIDTH if is_selected else 0
        border_color = SELECTED_BORDER_COLOR if is_selected else None
        username = account_data.get("username", "Unnamed")
        logging.debug(f"Creating item for index {index}, user '{username}', state: {current_state}, selected: {is_selected}")

        item_frame = ctk.CTkFrame(
            parent_frame,
            fg_color=FRAME_COLOR,
            corner_radius=10,
            height=ACCOUNT_ITEM_HEIGHT,
            border_width=border_width,
            border_color=border_color
        )
        item_frame.pack(fill="x", pady=ACCOUNT_ITEM_PADY, padx=ACCOUNT_ITEM_PADX)
        item_frame.pack_propagate(False)

        item_frame.grid_columnconfigure(0, weight=1)  # Username label
        item_frame.grid_columnconfigure(1, weight=0)  # Status label
        item_frame.grid_columnconfigure(2, weight=0)  # Delete button

        username_label = ctk.CTkLabel(
            item_frame,
            text=username,
            font=FONT_TITLE,
            text_color=TEXT_COLOR,
            anchor="w"
        )
        username_label.grid(row=0, column=0, padx=(15, 5), pady=0, sticky="w")

        # Status Label
        status_text = ""
        if current_state == 'loading':
            status_text = "⏳ Loading"
        elif current_state == 'running':
            status_text = "✓ Running"
        status_label = ctk.CTkLabel(
            item_frame,
            text=status_text,
            font=FONT_STATUS,
            text_color=(STATUS_LOADING_COLOR if current_state == 'loading' else STATUS_RUNNING_COLOR),
            anchor="w"
        )
        status_label.grid(row=0, column=1, padx=5, pady=0, sticky="w")
        self.status_labels[profile_dir_name] = status_label

        delete_button = ctk.CTkButton(
            item_frame,
            text="✖",
            command=lambda idx=index: self.delete_account_by_index(idx),
            width=30,
            height=30,
            corner_radius=15,
            fg_color="transparent",
            text_color=DELETE_COLOR,
            hover_color=FRAME_COLOR,
            font=("Segoe UI", 16, "bold")
        )
        delete_button.grid(row=0, column=2, padx=(0, 10), pady=5, sticky="e")

        # Bindings for selection and double-click to launch
        item_frame.bind("<Button-1>", lambda event, idx=index: self.select_account(idx))
        username_label.bind("<Button-1>", lambda event, idx=index: self.select_account(idx))
        launch_func = lambda event, idx=index, p_name=profile_dir_name: self.launch_profile_threaded(idx, p_name)
        item_frame.bind("<Double-Button-1>", launch_func)
        username_label.bind("<Double-Button-1>", launch_func)

    def select_account(self, index):
        """Selects an account and updates the display."""
        if 0 <= index < len(self.accounts):
            if self.current_account_index != index:
                self.current_account_index = index
                self.update_account_list_display()
                logging.info(f"Selected account index: {index}, User: {self.accounts[index]['username']}")
            else:
                logging.debug(f"Account index {index} already selected.")
        else:
            logging.warning(f"Invalid index for selection: {index}")

    def add_random_account(self):
        """Adds a new account with a randomly generated username."""
        username = f"User_{uuid.uuid4().hex[:8]}"
        logging.info(f"Adding account with username: {username}")
        while any(acc['username'] == username for acc in self.accounts):
            logging.warning(f"Username collision detected for '{username}'. Regenerating.")
            username = f"User_{uuid.uuid4().hex[:10]}"

        profile_dir_name = sanitize_filename(username)
        existing_profile_names = {acc.get("profile_dir_name") for acc in self.accounts}
        count = 1
        original_name = profile_dir_name
        while profile_dir_name in existing_profile_names:
            profile_dir_name = f"{original_name}_{count}"
            count += 1

        profile_path = self.profiles_base_dir / profile_dir_name
        try:
            profile_path.mkdir(parents=True, exist_ok=True)
            logging.info(f"Created profile directory for new account: {profile_path}")
        except OSError as e:
            logging.error(f"Failed to create directory {profile_path} for '{username}': {e}")
            self.display_critical_error(f"Could not create directory:\n{profile_path}\nError: {e}")
            return

        new_account_data = {"username": username, "profile_dir_name": profile_dir_name}
        self.accounts.append(new_account_data)
        self.profile_states[profile_dir_name] = 'idle'
        save_accounts(self.accounts)
        self.current_account_index = len(self.accounts) - 1
        self.update_account_list_display()
        logging.info(f"Added account: Username='{username}', Profile='{profile_dir_name}'")

    def delete_account_by_index(self, index):
        """Deletes an account entry along with its state and label references."""
        if not (0 <= index < len(self.accounts)):
            logging.warning(f"Invalid index for deletion: {index}")
            return

        deleted_account = self.accounts.pop(index)
        username = deleted_account.get('username', 'N/A')
        profile_name = deleted_account.get('profile_dir_name')
        if profile_name:
            logging.info(f"Deleting account: User='{username}', Profile='{profile_name}'")
            if profile_name in self.profile_states:
                del self.profile_states[profile_name]
            if profile_name in self.status_labels:
                del self.status_labels[profile_name]
            if profile_name in self.profile_last_launch:
                del self.profile_last_launch[profile_name]
        else:
            logging.error(f"Account '{username}' missing profile_dir_name during deletion.")

        # Note: Profile directory is not deleted.
        save_accounts(self.accounts)
        if not self.accounts:
            self.current_account_index = -1
        elif index <= self.current_account_index:
            self.current_account_index = max(0, self.current_account_index - 1)
            self.current_account_index = min(self.current_account_index, len(self.accounts) - 1)

        self.update_account_list_display()

    def launch_profile_threaded(self, index, profile_dir_name):
        """Launches the browser for the selected profile in a new thread if idle."""
        logging.debug(f"Launch requested for index {index}, profile '{profile_dir_name}'")
        current_state = self.profile_states.get(profile_dir_name, 'idle')
        if current_state != 'idle':
            logging.warning(f"Profile '{profile_dir_name}' is already in state '{current_state}'.")
            return

        if not (0 <= index < len(self.accounts)):
            logging.error(f"Invalid account index {index} for launch.")
            return

        self._set_profile_state(profile_dir_name, 'loading')
        account_info = self.accounts[index]
        username = account_info.get("username", "N/A")
        profile_path = self.profiles_base_dir / profile_dir_name
        if not profile_path.is_dir():
            logging.error(f"Profile directory for '{username}' not found at {profile_path}. Attempting to recreate.")
            try:
                profile_path.mkdir(parents=True, exist_ok=True)
                logging.info(f"Recreated missing profile directory: {profile_path}")
            except OSError as e:
                logging.error(f"Failed to recreate directory {profile_path}: {e}")
                self.display_critical_error(f"Failed to create directory:\n{profile_path}\nError: {e}")
                self._set_profile_state(profile_dir_name, 'idle')
                return

        logging.info(f"Starting browser launch thread for '{username}' (Profile: {profile_dir_name})")
        thread = threading.Thread(
            target=self._run_browser_instance,
            args=(profile_dir_name, username),
            daemon=True,
            name=f"BrowserThread-{profile_dir_name}"
        )
        thread.start()

    def _run_browser_instance(self, profile_dir_name, username):
        """
        Worker thread function to launch and monitor the Chrome instance.
        It also tracks the launch timestamp.
        """
        logging.info(f"Browser thread started for profile '{profile_dir_name}'")
        driver = None
        launch_start = time.time()
        try:
            options = uc.ChromeOptions()
            user_data_dir_path = str(self.profiles_base_dir.resolve())
            options.add_argument(f'--profile-directory={profile_dir_name}')
            options.add_argument('--start-maximized')
            options.add_argument('--no-first-run')
            options.add_argument('--no-default-browser-check')
            logging.debug(f"Chrome Options prepared for profile '{profile_dir_name}'")
            driver = uc.Chrome(options=options, user_data_dir=user_data_dir_path)
            launch_duration = time.time() - launch_start
            logging.info(f"uc.Chrome instance created for '{profile_dir_name}' in {launch_duration:.2f} seconds.")

            # Record last launch time for switching purposes.
            self.profile_last_launch[profile_dir_name] = launch_start

            self._set_profile_state(profile_dir_name, 'running')

            try:
                driver.get("https://chatgpt.com/")
                nav_duration = time.time() - launch_start - launch_duration
                logging.info(f"Navigation completed for '{profile_dir_name}' in {nav_duration:.2f} seconds.")
            except Exception as nav_exc:
                logging.error(f"Error navigating for {profile_dir_name}: {nav_exc}")

            while True:
                if driver.service.process.poll() is not None:
                    logging.info(f"Browser process for '{profile_dir_name}' terminated.")
                    break
                time.sleep(1)
        except Exception as e:
            logging.exception(f"Error launching/running browser for profile '{profile_dir_name}': {e}")
            self.after(0, lambda: self.display_critical_error(f"Failed to launch Chrome for '{username}'.\nError: {e}\nCheck logs."))
        finally:
            logging.info(f"Browser thread ending for '{profile_dir_name}'. Cleaning up.")
            if driver:
                try:
                    driver.quit()
                    logging.debug(f"driver.quit() called for '{profile_dir_name}'")
                except Exception as e_quit:
                    logging.warning(f"Error during driver.quit() for '{profile_dir_name}': {e_quit}")
            self._set_profile_state(profile_dir_name, 'idle')

    def switch_account(self):
        """
        Finds and launches the account which has been opened (launched) the longest time ago,
        ignoring those that have never been launched.
        """
        candidate = None
        oldest_timestamp = None
        for acc in self.accounts:
            p_dir = acc.get("profile_dir_name")
            # Only consider accounts that have a recorded launch time
            if p_dir in self.profile_last_launch and self.profile_states.get(p_dir, 'idle') == 'idle':
                timestamp = self.profile_last_launch[p_dir]
                if oldest_timestamp is None or timestamp < oldest_timestamp:
                    oldest_timestamp = timestamp
                    candidate = acc
        if candidate:
            index = self.accounts.index(candidate)
            logging.info(f"Switching to account: {candidate.get('username')} (Profile: {candidate.get('profile_dir_name')})")
            self.launch_profile_threaded(index, candidate.get("profile_dir_name"))
        else:
            logging.info("No eligible account found for switching. Make sure some accounts have been launched before.")
            try:
                messagebox.showinfo("Switch", "No eligible account found for switching.\n(Only accounts that have been launched before are eligible.)")
            except Exception as ex:
                logging.error(f"Failed to display switch info: {ex}")

    def on_closing(self):
        """Handles window close events with confirmation if any browser is still running."""
        running_profiles = [p for p, state in self.profile_states.items() if state == 'running']
        if running_profiles:
            answer = messagebox.askyesno("Confirm Exit", "One or more browsers are still running.\nAre you sure you want to exit?")
            if not answer:
                return
        logging.info("Exiting application. Cleaning up.")
        self.destroy()

# --- Main Execution ---
if __name__ == "__main__":
    logging.info("Starting Account Manager Application...")
    try:
        app = AccountSwitcher()
        if hasattr(app, 'profiles_base_dir'):
            app.mainloop()
        else:
            logging.error("Application initialization failed. Exiting.")
    except Exception as main_e:
        logging.critical(f"Unhandled exception: {main_e}", exc_info=True)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Critical Error", f"An unexpected error occurred:\n{main_e}\nCheck logs.")
            root.destroy()
        except Exception as fallback_e:
            logging.error(f"Failed to display fallback error: {fallback_e}")
    finally:
        logging.info("Application finished.")
