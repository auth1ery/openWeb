# openWeb9.py
# Version 1.8
# full fucking revamp

import sys
import os
import json
import logging
import requests
import ntpath
import threading
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse

from PyQt5.QtCore import QUrl, QTimer, Qt, QSettings, QStandardPaths, QByteArray
from PyQt5.QtWidgets import (
	QApplication,
	QMainWindow,
	QWidget,
	QVBoxLayout,
	QHBoxLayout,
	QLineEdit,
	QLabel,
	QTabWidget,
	QToolBar,
	QAction,
	QDialog,
	QPushButton,
	QListWidget,
	QSlider,
)
from PyQt5.QtWebEngineWidgets import (
	QWebEngineView,
	QWebEngineProfile,
)
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
from PyQt5.QtWidgets import QFrame

# ---------- config ----------
BLOCKLIST_URLS = [
	"https://easylist.to/easylist/easylist.txt",
	# "https://easylist.to/fanboy/fanboy-annoyance.txt"
]

# Domains you never want to block (exact/endswith)
ALLOWLIST = {"example.com", "mysite.org"}

# ---------- logging ----------
logging.basicConfig(
	filename="openweb.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------- files & paths ----------
APP_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openweb_data")

# debug
print("REAL APP_DATA_DIR:", APP_DATA_DIR)
print("ABSOLUTE:", os.path.abspath(APP_DATA_DIR))
print("CWD:", os.getcwd())
print("EXISTS:", os.path.exists(APP_DATA_DIR))
print("FULL CONTENTS:")
for root, dirs, files in os.walk(APP_DATA_DIR):
	for f in files:
		print(os.path.join(root, f))
os.makedirs(APP_DATA_DIR, exist_ok=True)

BOOKMARK_FILE = os.path.join(APP_DATA_DIR, "bookmarks.json")
SESSION_FILE = os.path.join(APP_DATA_DIR, "session.json")
EXTENSIONS_DIR = os.path.join(APP_DATA_DIR, "extensions")
os.makedirs(EXTENSIONS_DIR, exist_ok=True)
EXT_STATE_FILE = os.path.join(APP_DATA_DIR, "extensions_state.json")


# ---------- AdBlocker ----------
class AdBlocker(QWebEngineUrlRequestInterceptor):
	def __init__(self, parent=None):
		super().__init__(parent)
		# store normalized domains in a set for fast suffix checks (e.g. example.com)
		self._domains = set()
		self.last_update = datetime.min
		self._lock = threading.Lock()
		self._updating = False
		# Kick off an initial update in background (guarded)
		self._start_update_thread()

	def _start_update_thread(self):
		# Ensure only one update thread runs at a time.
		with self._lock:
			if self._updating:
				return
			self._updating = True

		def worker():
			try:
				self.update_blocklist()
			finally:
				with self._lock:
					self._updating = False

		threading.Thread(target=worker, daemon=True).start()

	def update_blocklist(self):
		"""Fetch lists in a background thread and populate self._domains."""
		domains = set()
		for url in BLOCKLIST_URLS:
			try:
				r = requests.get(url, timeout=10)
				r.raise_for_status()
				for line in r.text.splitlines():
					line = line.strip()
					# only simple domain rules like "||domain^"
					if line.startswith("||") and line.endswith("^"):
						domain = line[2:-1].lower()
						if domain:
							domains.add(domain.lstrip("."))
				logging.info(f"[AdBlocker] Loaded blocklist: {url}")
			except Exception as e:
				logging.warning(f"[AdBlocker] Failed to fetch {url}: {e}")

		with self._lock:
			self._domains = domains
			self.last_update = datetime.now()
		logging.info(f"[AdBlocker] Total domains loaded: {len(domains)}")

	def maybe_update_blocklist(self):
		# Only start an update if it's been more than a day and no update is currently running.
		with self._lock:
			need = (datetime.now() - self.last_update > timedelta(days=1)) and (not self._updating)
		if need:
			self._start_update_thread()

	def interceptRequest(self, info):
		# called from Qt's network thread; keep it fast and thread-safe
		try:
			# Schedule periodic update if needed (non-blocking)
			self.maybe_update_blocklist()
			url = info.requestUrl().toString().lower()
			host = urlparse(url).netloc.split(":")[0]  # drop ports
			if not host:
				return
			host = host.strip(".")
			# allowlist check
			for a in ALLOWLIST:
				if host == a or host.endswith("." + a):
					return
			# quick suffix-check using stored domains (thread-safe read)
			with self._lock:
				domains = set(self._domains)
			if domains and self._host_matches_any_domain(host, domains):
				info.block(True)
		except Exception:
			# never crash in the interceptor; if something goes wrong, just don't block
			logging.exception("AdBlocker interceptRequest failed")

	@staticmethod
	def _host_matches_any_domain(host, domains_set):
		# Check host suffixes: for "a.b.c.example.com" check:
		# example.com, c.example.com, b.c.example.com, ...
		labels = host.split(".")
		# go from the shortest suffix to longest: example.com, c.example.com, etc.
		for i in range(len(labels) - 1):
			suffix = ".".join(labels[i:])
			if suffix in domains_set:
				return True
		return False

# ---------- Browser ----------
class OldInternetBrowser(QMainWindow):
	def __init__(self):
		super().__init__()
		
		self.first_run = not os.path.exists(EXT_STATE_FILE)
		if self.first_run:
			logging.info("First run detected: all extensions will start disabled.")

		self.setWindowTitle("openWeb Browser")
		self.setGeometry(100, 100, 900, 700)

		# keep a persistent reference so it's not garbage collected
		self.adblocker = AdBlocker(self)
		QWebEngineProfile.defaultProfile().setRequestInterceptor(self.adblocker)

		# UI
		self.tabs = QTabWidget()
		self.tabs.setTabsClosable(True)
		self.tabs.tabCloseRequested.connect(self.close_tab)
		self.setCentralWidget(self.tabs)

		self.toolbar = QToolBar()
		self.addToolBar(self.toolbar)

		self.url_bar = QLineEdit()
		self.url_bar.returnPressed.connect(self.start_loading)
		self.toolbar.addWidget(self.url_bar)

		tools = {
			"<-": self.go_back,
			"->": self.go_forward,
			"Reload": self.reload_page,
			"New Tab": self.new_tab,
			"Manager": self.open_manager,
			"Bookmarks": self.open_bookmarks,
			"Mixer": self.open_tab_mixer,
			"Extensions": self.open_local_extensions_store,
		}
		for label, slot in tools.items():
			act = QAction(label, self)
			act.triggered.connect(slot)
			self.toolbar.addAction(act)

		self.setStyleSheet(
			"""
			QMainWindow { background:#c0c0c0; }
			QToolBar { background:#e0e0e0; }
			QLineEdit { font-family:Courier; font-size:12px; }
		"""
		)

		self.status_label = QLabel("Status: Ready")
		self.status_label.setStyleSheet("background:#e0e0e0; font-family:Courier; font-size:12px;")
		self.statusBar().addWidget(self.status_label)

		# state
		self.bookmarks = self.load_bookmarks()
		self.extensions = []  # populated below
		# UI init
		self.new_tab()
		# load/restore data
		self.restore_session()
		# load extensions (local + remote) without blocking UI
		self.load_local_extensions()
		self.load_remote_extensions_async()
		self.restore_extensions_state()
		if self.first_run:
			popup = QLabel("All extensions are disabled by default. You can enable them in Extensions Store.", self)
			popup.setStyleSheet("background: yellow; color: black; padding: 6px; border: 1px solid black;")
			popup.setWindowFlags(Qt.ToolTip)
			popup.move(50, 50)
			popup.show()
			QTimer.singleShot(8000, lambda: popup.deleteLater())  # hide after 8s


		# geometry restore: only if previously saved
		s = QSettings("openWeb", "browser")
		geom = s.value("geometry")
		if isinstance(geom, (bytes, QByteArray)) and geom:
			try:
				self.restoreGeometry(QByteArray(geom))
			except Exception:
				# sometimes QSettings returns a QVariant-wrapped QByteArray; try direct call
				try:
					self.restoreGeometry(geom)
				except Exception:
					logging.warning("Failed to restore geometry")

		self.tabs.currentChanged.connect(lambda _: self.save_geometry())

	# ------ session handling ------
	def save_session(self):
		logging.info("Saving session")
		session_data = []
		for i in range(self.tabs.count()):
			page_widget = self.tabs.widget(i)
			if not page_widget:
				continue
			b = page_widget.findChild(QWebEngineView)
			if b:
				url_str = b.url().toString()
				if url_str:
					session_data.append(url_str)
		try:
			with open(SESSION_FILE, "w", encoding="utf-8") as f:
				json.dump(session_data, f, indent=2)
			logging.info("Session saved")
		except Exception:
			logging.exception("Error saving session")

	def restore_session(self):
		logging.info("Restoring session")
		if not os.path.exists(SESSION_FILE):
			return
		try:
			with open(SESSION_FILE, "r", encoding="utf-8") as f:
				urls = json.load(f)
			if urls:
				self.tabs.clear()
				for url in urls:
					self.new_tab()
					b = self.tabs.currentWidget().findChild(QWebEngineView)
					if b:
						b.load(QUrl(url))
			logging.info("Session restored")
		except Exception:
			logging.exception("Error restoring session")

	# ------ extensions (remote in background) ------
	def load_remote_extensions_async(self):
		# spawn thread to fetch remote scripts; injection will happen in main thread
		threading.Thread(target=self._load_remote_extensions, daemon=True).start()

	def _add_remote_extension(self, ext):
		"""Add a remote extension to the main-thread extensions list and inject if enabled/content present."""
		# avoid duplicates by name
		if not any(e.get("name") == ext.get("name") for e in self.extensions):
			self.extensions.append(ext)
			if ext.get("enabled", True) and ext.get("content"):
				# inject into current browser (preserve original behavioral intent)
				try:
					self.inject_extension(ext)
				except Exception:
					logging.exception("Failed to inject remote extension on main thread")

	def _load_remote_extensions(self):
		# background thread
		remote_extensions = [
			{
				"name": "Dark Mode",
				"url": "https://auth1ery.github.io/openWeb/dark_mode.js",
				"enabled": True,
				"remote": True,
			},
			{
				"name": "Reading Mode",
				"url": "https://auth1ery.github.io/openWeb/reading_mode.js",
				"enabled": True,
				"remote": True,
			},
		]

		# set enabled state based on first run or saved state
		saved_states = {}
		if os.path.exists(EXT_STATE_FILE):
			try:
				with open(EXT_STATE_FILE, "r", encoding="utf-8") as f:
					for s in json.load(f):
						saved_states[s.get("name")] = s.get("enabled", True)
			except Exception:
				logging.exception("Failed to load saved extension states")

		# Process remote extensions: fetch content, then schedule add on main thread
		for ext_meta in remote_extensions:
			try:
				name = ext_meta.get("name")
				ext = dict(ext_meta)  # copy
				# determine enabled
				if self.first_run:
					ext["enabled"] = False
				else:
					ext["enabled"] = saved_states.get(name, ext.get("enabled", True))
				# attempt to fetch content (best-effort)
				try:
					r = requests.get(ext.get("url"), timeout=10)
					r.raise_for_status()
					ext["content"] = r.text
					logging.info(f"Fetched remote extension content: {name}")
				except Exception:
					logging.warning(f"Failed to fetch remote extension {name}; will add without content.")
				# schedule add on main thread
				QTimer.singleShot(0, lambda e=ext: self._add_remote_extension(e))
			except Exception:
				logging.exception("Error processing remote extension metadata")

	def load_local_extensions(self):
		saved_states = {}
		if os.path.exists(EXT_STATE_FILE):
			try:
				with open(EXT_STATE_FILE, "r", encoding="utf-8") as f:
					for s in json.load(f):
						saved_states[s.get("name")] = s.get("enabled", True)
			except Exception:
				logging.exception("Failed to load saved extension states")

		try:
			for ext_name in os.listdir(EXTENSIONS_DIR):
				ext_path = os.path.join(EXTENSIONS_DIR, ext_name)
				if not os.path.isdir(ext_path):
					continue
				manifest_file = os.path.join(ext_path, "manifest.json")
				if os.path.exists(manifest_file):
					try:
						with open(manifest_file, "r", encoding="utf-8") as f:
							manifest = json.load(f)
						manifest["path"] = ext_path
						# avoid duplicates by name
						if not any(e.get("name") == manifest.get("name") for e in self.extensions):
							self.extensions.append(manifest)
						# set enabled state: first run = False, else saved state
						if self.first_run:
							manifest["enabled"] = False
						else:
							manifest["enabled"] = saved_states.get(manifest.get("name"), manifest.get("enabled", True))
						# inject if enabled
						if manifest.get("enabled", True):
							QTimer.singleShot(0, lambda m=manifest: self.inject_extension(m))
					except Exception:
						logging.exception(f"Failed to load local extension {ext_name}")
		except Exception:
			logging.exception("Error enumerating local extensions directory")


	def inject_extension(self, ext):
		"""Inject JS or execute Python scripts for an extension object."""
		try:
			# remote js content case
			if ext.get("content") and ext.get("enabled", True):
				b = self.current_browser()
				if b:
					b.page().runJavaScript(ext["content"])
					logging.info(f"[Extensions] Injected remote content: {ext.get('name')}")
				return

			# local script files case (manifest usually has "scripts": [])
			scripts = ext.get("scripts", [])
			if not scripts:
				return
			for script in scripts:
				script_path = os.path.join(ext.get("path", ""), script)
				if not os.path.exists(script_path):
					logging.warning(f"Script not found: {script_path}")
					continue
				if script.endswith(".py"):
					# execute with limited globals; still dangerous but keeping old behavior
					try:
						with open(script_path, "r", encoding="utf-8") as f:
							code = f.read()
						exec(code, {"browser": self})
						logging.info(f"Executed python extension: {script}")
					except Exception:
						logging.exception(f"Error executing python extension {script}")
				elif script.endswith(".js"):
					try:
						with open(script_path, "r", encoding="utf-8") as f:
							js_code = f.read()
						b = self.current_browser()
						if b:
							b.page().runJavaScript(js_code)
							logging.info(f"Injected js extension: {script}")
					except Exception:
						logging.exception(f"Error injecting js extension {script}")
		except Exception:
			logging.exception("inject_extension failed")

	# extension state save/restore
	def save_extensions_state(self):
		state = [{"name": ext.get("name"), "enabled": ext.get("enabled", True)} for ext in self.extensions if ext.get("name")]
		try:
			with open(EXT_STATE_FILE, "w", encoding="utf-8") as f:
				json.dump(state, f, indent=2)
			logging.info("Saved extension states.")
		except Exception:
			logging.exception("Failed to save extension states")

	def restore_extensions_state(self):
		if not os.path.exists(EXT_STATE_FILE):
			return
		try:
			with open(EXT_STATE_FILE, "r", encoding="utf-8") as f:
				saved = json.load(f)
			mapping = {s["name"]: s.get("enabled", True) for s in saved if "name" in s}
			for ext in self.extensions:
				if ext.get("name") in mapping:
					ext["enabled"] = mapping[ext["name"]]
			logging.info(f"Restored {len(mapping)} extension states.")
		except Exception:
			logging.exception("Failed to restore extension states")

	# ------ extensions UI ------
	def open_local_extensions_store(self):
		dialog = QDialog(self)
		dialog.setWindowTitle("Extensions Store")
		dialog.setGeometry(250, 250, 500, 400)
		layout = QVBoxLayout(dialog)

		list_widget = QListWidget()
		for ext in self.extensions:
			status = "[Enabled]" if ext.get("enabled", True) else "[Disabled]"
			list_widget.addItem(f"{ext.get('name', '(unnamed)')} {status}")
		layout.addWidget(list_widget)

		toggle_btn = QPushButton("Toggle Enable/Disable")
		reload_btn = QPushButton("Reload Extension")
		layout.addWidget(toggle_btn)
		layout.addWidget(reload_btn)

		def toggle():
			selected = list_widget.currentRow()
			if selected < 0:
				return
			ext = self.extensions[selected]
			ext["enabled"] = not ext.get("enabled", True)
			list_widget.item(selected).setText(
				f"{ext.get('name', '(unnamed)')} {'[Enabled]' if ext['enabled'] else '[Disabled]'}"
			)
			# if local, save manifest if present
			if ext.get("path"):
				manifest_path = os.path.join(ext["path"], "manifest.json")
				try:
					# write only manifest-like info back to manifest.json to avoid polluting it with runtime-only keys
					manifest_to_save = {k: v for k, v in ext.items() if k in ("name", "version", "description", "scripts", "enabled")}
					with open(manifest_path, "w", encoding="utf-8") as f:
						json.dump(manifest_to_save, f, indent=2)
				except Exception:
					logging.exception(f"Failed to save manifest for {ext.get('name')}")
			else:
				logging.info(f"'{ext.get('name')}' is remote; not saving manifest locally.")
			self.save_extensions_state()

		def reload_ext():
			selected = list_widget.currentRow()
			if selected < 0:
				return
			ext = self.extensions[selected]
			# for remote ext, content may exist; for local, re-read files
			if ext.get("remote") and ext.get("url"):
				def fetch_and_inject():
					try:
						r = requests.get(ext["url"], timeout=10)
						r.raise_for_status()
						ext["content"] = r.text
						logging.info(f"Refreshed remote extension {ext.get('name')}")
						QTimer.singleShot(0, lambda e=ext: self.inject_extension(e))
					except Exception:
						logging.exception(f"Failed to reload remote extension {ext.get('name')}")
				threading.Thread(target=fetch_and_inject, daemon=True).start()
			else:
				# re-inject local scripts immediately on main thread
				self.inject_extension(ext)

		# Connect manager buttons to their actions
		toggle_btn.clicked.connect(toggle)
		reload_btn.clicked.connect(reload_ext)

		dialog.setLayout(layout)
		dialog.exec_()

	# ------ downloads ------
	def setup_downloads(self, browser: QWebEngineView):
		# connection method expects a callable that accepts QWebEngineDownloadItem
		profile = browser.page().profile()
		profile.downloadRequested.connect(self.handle_download)

	def handle_download(self, download):
		try:
			filename = ntpath.basename(download.path()) or "download"
			downloads_path = Path.home() / "Downloads" / filename
			download.setPath(str(downloads_path))
			download.accept()

			popup = QLabel(f"Downloading '{filename}'... Check the status at the bottom.", self)
			popup.setStyleSheet("background: yellow; color: black; padding: 4px; border: 1px solid black;")
			popup.setWindowFlags(Qt.ToolTip)
			popup.move(10, 10)
			popup.show()
			QTimer.singleShot(3000, lambda: popup.deleteLater())

			self.status_label.setText(f"Status: Downloading '{filename}'...")
			download.finished.connect(lambda: self.status_label.setText(f"Status: Download finished: '{filename}'"))
		except Exception:
			logging.exception("handle_download failed")

	# ------ bookmarks ------
	def load_bookmarks(self):
		if os.path.exists(BOOKMARK_FILE):
			try:
				with open(BOOKMARK_FILE, "r", encoding="utf-8") as f:
					return json.load(f)
			except Exception:
				logging.exception("Error loading bookmarks")
				return []
		return []

	def save_bookmarks(self):
		tmp = BOOKMARK_FILE + ".tmp"
		try:
			with open(tmp, "w", encoding="utf-8") as f:
				json.dump(self.bookmarks, f, indent=2)
			os.replace(tmp, BOOKMARK_FILE)
		except Exception:
			logging.exception("Error saving bookmarks")
			if os.path.exists(tmp):
				try:
					os.remove(tmp)
				except Exception:
					pass

	# ------ browser tabs & navigation ------
	def current_browser(self):
		page = self.tabs.currentWidget()
		return page.findChild(QWebEngineView) if page else None

	def new_tab(self):
		page = QWidget()
		layout = QVBoxLayout(page)
		browser = QWebEngineView()
		self.setup_downloads(browser)
		browser.setHtml("<h1>Welcome to openWeb!</h1><p>Type a URL above to surf.</p><p>Version 1.8</p>")
		# title change handler
		browser.titleChanged.connect(
			lambda t, w=page: self.tabs.setTabText(self.tabs.indexOf(w), (t[:15] + ("..." if len(t) > 15 else "")) if t else "Tab")
		)
		# inject extensions after load
		browser.loadFinished.connect(lambda ok, b=browser: self.inject_all_extensions(b) if ok else None)
		layout.addWidget(browser)
		self.tabs.addTab(page, f"Tab {self.tabs.count() + 1}")
		self.tabs.setCurrentWidget(page)

	def close_tab(self, i):
		if self.tabs.count() > 1:
			self.tabs.removeTab(i)

	def go_back(self):
		b = self.current_browser()
		if b:
			b.back()
			self.status_label.setText("Status: Viewing")

	def go_forward(self):
		b = self.current_browser()
		if b:
			b.forward()
			self.status_label.setText("Status: Viewing")

	def reload_page(self):
		b = self.current_browser()
		if b:
			b.reload()
			self.status_label.setText("Status: Reloading...")

	# --- SMART URL / SEARCH ---
	def start_loading(self):
		b = self.current_browser()
		if not b:
			return
		text = self.url_bar.text().strip()
		if not text:
			return

		domain_pattern = r"^(?:http[s]?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/.*)?$"
		match = __import__("re").match(domain_pattern, text)
		if match:
			url = text
			if not url.startswith(("http://", "https://")):
				url = "https://" + url
			host = QUrl(url).host()
			path = match.group(2) or ""
			if not host.startswith("www.") and "/" not in path and host.count(".") <= 2:
				url = url.replace(host, "www." + host)
		else:
			url = "https://www.google.com/search?q=" + text.replace(" ", "+")

		self.loading_url = QUrl(url)
		self.status_label.setText("Status: Loading...")
		try:
			# Do not indiscriminately disconnect all loadFinished handlers.
			# Instead, add a one-off handler for check_load for this browser.
			b.loadFinished.connect(lambda ok, b=b: self.check_load(ok))
			b.load(self.loading_url)
		except Exception:
			logging.exception(f"Failed to load {url}")
			self.status_label.setText("Status: Failed to Load... :(")

	def check_load(self, ok):
		if not ok:
			self.status_label.setText("Status: Offline, check your internet.")
		else:
			self.status_label.setText("Status: Viewing")

	def save_geometry(self):
		s = QSettings("openWeb", "browser")
		try:
			s.setValue("geometry", self.saveGeometry())
		except Exception:
			logging.exception("save_geometry failed")

	# --- Manager ---
	def open_manager(self):
		dialog = QDialog(self)
		dialog.setWindowTitle("openWeb Manager")
		dialog.setGeometry(200, 200, 320, 220)

		layout = QVBoxLayout(dialog)
		layout.addWidget(QLabel("Browser Data Controls (global)"))

		clear_cache = QPushButton("Clear Cache")
		clear_cookies = QPushButton("Clear Cookies")
		layout.addWidget(clear_cache)
		layout.addWidget(clear_cookies)

		# separator line
		line = QFrame()
		line.setFrameShape(QFrame.HLine)
		line.setFrameShadow(QFrame.Sunken)
		layout.addWidget(line)

		# reset all data button
		reset_all = QPushButton("Reset All Data")
		reset_all.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
		layout.addWidget(reset_all)

		profile = QWebEngineProfile.defaultProfile()

		def clear_cache_action():
			try:
				profile.clearHttpCache()
				clear_cache.setText("Cache Cleared!")
			except Exception:
				logging.exception("Failed clearing cache")

		def clear_cookies_action():
			try:
				profile.cookieStore().deleteAllCookies()
				clear_cookies.setText("Cookies Cleared!")
			except Exception:
				logging.exception("Failed clearing cookies")

		def reset_all_action():
			try:
				profile = QWebEngineProfile.defaultProfile()
				# clear Qt caches/cookies too
				try:
					profile.clearHttpCache()
					profile.cookieStore().deleteAllCookies()
				except Exception:
					logging.exception("Failed to clear profile data during reset")

				# files to delete in APP_DATA_DIR
				targets = ["bookmarks.json", "session.json", "extensions_state.json"]
				for filename in targets:
					path = os.path.join(APP_DATA_DIR, filename)
					if os.path.exists(path):
						try:
							os.remove(path)
							logging.info(f"Removed {path}")
						except Exception:
							logging.exception(f"Failed to remove {path}")

				# remove local extension folders completely
				if os.path.exists(EXTENSIONS_DIR):
					try:
						for name in os.listdir(EXTENSIONS_DIR):
							path = os.path.join(EXTENSIONS_DIR, name)
							if os.path.isdir(path):
								shutil.rmtree(path, ignore_errors=True)
								logging.info(f"Removed extension folder {path}")
					except Exception:
						logging.exception("Failed to remove extensions directory contents")

				# clear in-memory extension list so they won't be re-injected this session
				try:
					self.extensions.clear()
				except Exception:
					logging.exception("Failed to clear in-memory extensions list")

				# remove likely injected styles/scripts from each open page (best-effort)
				try:
					for i in range(self.tabs.count()):
						page = self.tabs.widget(i)
						b = page.findChild(QWebEngineView) if page else None
						if b:
							# remove <style> and <link> that extensions might have injected (best-effort markerless cleanup)
							js_remove = """
							try {
							  document.querySelectorAll('style, link[rel=stylesheet]').forEach(n=>{
								// heuristics: if a stylesheet node contains extension-like rules (e.g., 'highlight-links' or common extension selectors),
								// we remove it. This is intentionally broad; it's best-effort and non-destructive to deep page CSS.
								try {
								  const text = (n.innerText || n.href || '').toLowerCase();
								  if (text.includes('highlight') || text.includes('extension') || text.includes('openweb')) {
									n.remove();
								  }
								} catch(e){}
							  });
							} catch(e){}
							"""
							b.page().runJavaScript(js_remove)
							b.reload()
				except Exception:
					logging.exception("Failed to scrub pages")

				reset_all.setText("All Data Reset!")
			except Exception:
				logging.exception("Failed resetting all data")

		# connect manager buttons
		clear_cache.clicked.connect(clear_cache_action)
		clear_cookies.clicked.connect(clear_cookies_action)
		reset_all.clicked.connect(reset_all_action)

	# --- Bookmarks ---
	def open_bookmarks(self):
		dialog = QDialog(self)
		dialog.setWindowTitle("Bookmarks")
		dialog.setGeometry(250, 250, 400, 400)
		layout = QVBoxLayout(dialog)
		list_widget = QListWidget()
		for bm in self.bookmarks:
			list_widget.addItem(f"{bm.get('title', 'Untitled')} - {bm.get('url', '')}")
		layout.addWidget(list_widget)
		add_btn = QPushButton("Add Current Page")
		del_btn = QPushButton("Delete Selected")
		layout.addWidget(add_btn)
		layout.addWidget(del_btn)

		def add_bookmark():
			b = self.current_browser()
			if not b:
				return
			url = b.url().toString()
			title = b.title() or url or "Untitled"
			self.bookmarks.append({"title": title, "url": url})
			self.save_bookmarks()
			list_widget.addItem(f"{title} - {url}")

		def del_bookmark():
			selected = list_widget.currentRow()
			if selected >= 0:
				list_widget.takeItem(selected)
				try:
					self.bookmarks.pop(selected)
					self.save_bookmarks()
				except Exception:
					logging.exception("Error deleting bookmark")

		def open_selected():
			selected = list_widget.currentRow()
			if selected >= 0 and selected < len(self.bookmarks):
				url = self.bookmarks[selected]["url"]
				self.url_bar.setText(url)
				self.start_loading()

		list_widget.itemDoubleClicked.connect(lambda _: open_selected())
		add_btn.clicked.connect(add_bookmark)
		del_btn.clicked.connect(del_bookmark)
		dialog.setLayout(layout)
		dialog.exec_()

	# --- Tab Volume Mixer ---
	def open_tab_mixer(self):
		dialog = QDialog(self)
		dialog.setWindowTitle("Tab Volume Mixer")
		dialog.setGeometry(300, 300, 350, 50 + 50 * max(1, self.tabs.count()))
		layout = QVBoxLayout(dialog)

		for i in range(self.tabs.count()):
			page = self.tabs.widget(i)
			browser = page.findChild(QWebEngineView)
			if not browser:
				continue

			tab_label = QLabel(self.tabs.tabText(i))
			tab_label.setFixedWidth(200)

			slider = QSlider(Qt.Horizontal)
			slider.setRange(0, 100)
			slider.setValue(100)

			def make_slider_callback(b=browser, s=slider):
				def callback():
					vol = s.value()
					# JS will clamp numbers; build valid JS arrow function with try/catch block
					try:
						js = "document.querySelectorAll('video,audio').forEach(el => { try { el.volume = %s; } catch(e) {} });" % (vol/100)
						b.page().runJavaScript(js)
					except Exception:
						logging.exception("Volume slider JS failed")
				return callback

			slider.valueChanged.connect(make_slider_callback())

			row = QHBoxLayout()
			row.addWidget(tab_label)
			row.addWidget(slider)
			layout.addLayout(row)

		dialog.setLayout(layout)
		dialog.exec_()

	# inject all enabled extensions' JS content into the given QWebEngineView
	def inject_all_extensions(self, browser):
		for ext in self.extensions:
			if ext.get("enabled", True):
				try:
					# remote content case
					if ext.get("content"):
						browser.page().runJavaScript(ext["content"])
						logging.info(f"[Extensions] Injected: {ext.get('name')}")
					# local scripts will be injected via inject_extension when loaded
				except Exception:
					logging.exception(f"Error injecting {ext.get('name')}")

	# override close event to save session & extension state
	def closeEvent(self, event):
		logging.info("App closing, saving session and extension state")
		try:
			self.save_session()
			self.save_extensions_state()
		except Exception:
			logging.exception("Error during close")
		super().closeEvent(event)


# ---------- main ----------
def main():
	app = QApplication(sys.argv)
	window = OldInternetBrowser()
	window.show()
	sys.exit(app.exec_())


if __name__ == "__main__":
	main()
