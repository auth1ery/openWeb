#!/usr/bin/env python3
# openWeb10.py
# Version 1.9

import sys
import os
import json
import requests
import ntpath
import threading
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse
import re

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
	QFrame,
)
from PyQt5.QtWebEngineWidgets import (
	QWebEngineView,
	QWebEngineProfile,
	QWebEngineSettings,
)

# ---------- config ----------
BLOCKLIST_URLS = [
	"https://easylist-downloads.adblockplus.org/easylist.txt",
]

# Domains you never want to block (exact or suffix)
ALLOWLIST = {"example.com", "mysite.org"}

# app data dir
APP_DATA_DIR = os.path.join(
	QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or os.path.expanduser("~"),
	"openweb"
)
os.makedirs(APP_DATA_DIR, exist_ok=True)

BOOKMARK_FILE = os.path.join(APP_DATA_DIR, "bookmarks.json")
SESSION_FILE = os.path.join(APP_DATA_DIR, "session.json")

# ---------- AdBlocker ----------
class AdBlocker:
	"""
	Lightweight adblocker using QWebEngineUrlRequestInterceptor if available.
	This class implements the domain matching logic and provides a Qt-friendly
	interceptor object via `interceptor()` when possible.
	"""

	def __init__(self, parent=None):
		self._domains = set()
		self.last_update = datetime.min
		self._lock = threading.Lock()
		self._updating = False
		# Start background update attempt (best-effort)
		self._start_update_thread()

	def _start_update_thread(self):
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
		domains = set()
		for url in BLOCKLIST_URLS:
			try:
				r = requests.get(url, timeout=10)
				r.raise_for_status()
				for line in r.text.splitlines():
					line = line.strip()
					# parse simple EasyList style domain rules like "||domain^"
					if line.startswith("||") and line.endswith("^"):
						domain = line[2:-1].lower().lstrip(".")
						if domain:
							domains.add(domain)
					# also accept plain domains on their own lines
					elif re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", line):
						domains.add(line.lower())
			except Exception:
				# swallow errors; blocklist is best-effort
				pass

		with self._lock:
			self._domains = domains
			self.last_update = datetime.now()

	def maybe_update_blocklist(self):
		with self._lock:
			need = (datetime.now() - self.last_update > timedelta(days=1)) and (not self._updating)
		if need:
			self._start_update_thread()

	def intercept_request(self, info):
		"""
		`info` is expected to be a QWebEngineUrlRequestInfo or similar.
		Keep this fast and safe — don't raise.
		"""
		try:
			self.maybe_update_blocklist()
			try:
				info.setHttpHeader(b"DNT", b"1")
				info.setHttpHeader(b"Sec-GPC", b"1")
			except Exception:
				pass

			url = info.requestUrl().toString().lower()
			host = urlparse(url).netloc.split(":")[0].strip(".")
			if not host:
				return
			# allowlist
			for a in ALLOWLIST:
				if host == a or host.endswith("." + a):
					return
			with self._lock:
				domains = set(self._domains)
			if domains and self._host_matches_any_domain(host, domains):
				info.block(True)
		except Exception:
			# never crash the networking stack
			pass

	@staticmethod
	def _host_matches_any_domain(host, domains_set):
		labels = host.split(".")
		# check suffixes from shortest to longest: example.com, c.example.com, ...
		for i in range(len(labels) - 1):
			suffix = ".".join(labels[i:])
			if suffix in domains_set:
				return True
		return False

	def make_qt_interceptor(self):
		"""
		Returns a QWebEngineUrlRequestInterceptor subclass instance that forwards
		to this object's intercept_request method. This avoids littering the
		rest of the codebase with platform-specific details.
		"""
		try:
			from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
		except Exception:
			return None

		parent = self

		class _Interceptor(QWebEngineUrlRequestInterceptor):
			def interceptRequest(self, info):
				parent.intercept_request(info)

		return _Interceptor()

# ---------- Browser ----------
class OldInternetBrowser(QMainWindow):
	def __init__(self):
		super().__init__()

		self.setWindowTitle("openWeb Browser")
		self.setGeometry(100, 100, 900, 700)

		# adblocker
		self.adblocker = AdBlocker(self)
		interceptor = self.adblocker.make_qt_interceptor()
		if interceptor is not None:
			QWebEngineProfile.defaultProfile().setRequestInterceptor(interceptor)

		profile = QWebEngineProfile.defaultProfile()
		# profile tweaks
		profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
		profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
		try:
			profile.setWebRTCIPHandlingPolicy(QWebEngineProfile.WebRTCDisableNonProxiedUdp)
		except Exception:
			# some environments may not expose this enum; ignore if unavailable
			pass

		# Settings via QWebEngineSettings for clarity
		settings = profile.settings()
		try:
			settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
			settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
			settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
			settings.setAttribute(QWebEngineSettings.AutoLoadImages, True)
			# optional: reduce GPU-ish features for small browsers
			settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, False)
			settings.setAttribute(QWebEngineSettings.WebGLEnabled, False)
		except Exception:
			pass

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
			"Stop": self.stop_loading,
			"Manager": self.open_manager,
			"Bookmarks": self.open_bookmarks,
			"Mixer": self.open_tab_mixer,
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
		self._scroll_timer = QTimer()
		self._scroll_timer.timeout.connect(self._scroll_status)
		self._scroll_timer.start(200)
		self._scroll_msg = "Ready"
		self._scroll_index = 0
		self.status_label.setStyleSheet("background:#e0e0e0; font-family:Courier; font-size:12px;")
		self.statusBar().addWidget(self.status_label)

		# state
		self.bookmarks = self.load_bookmarks()

		# UI init
		self.new_tab()
		# load/restore data
		self.restore_session()

		# geometry restore: only if previously saved
		s = QSettings("openWeb", "browser")
		geom = s.value("geometry")
		if isinstance(geom, (bytes, QByteArray)) and geom:
			try:
				self.restoreGeometry(QByteArray(geom))
			except Exception:
				try:
					self.restoreGeometry(geom)
				except Exception:
					pass

		self.tabs.currentChanged.connect(lambda _: self.save_geometry())

	# ------ session handling ------
	def save_session(self):
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
		except Exception:
			pass

	def restore_session(self):
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
		except Exception:
			pass

	# ------ downloads ------
	def setup_downloads(self, browser: QWebEngineView):
		profile = browser.page().profile()
		try:
			profile.downloadRequested.connect(self.handle_download)
		except Exception:
			# some PyQt builds may have different signal names; ignore if unavailable
			pass

	def handle_download(self, download):
		try:
			# Suggested filename
			suggested = ""
			try:
				suggested = download.downloadFileName()
			except Exception:
				try:
					suggested = ntpath.basename(download.path())
				except Exception:
					suggested = "download"
			if not suggested:
				suggested = "download"

			downloads_path = Path.home() / "Downloads" / suggested
			download.setPath(str(downloads_path))
			download.accept()

			popup = QLabel(f"Downloading '{suggested}'... Check the status at the bottom.", self)
			popup.setStyleSheet("background: yellow; color: black; padding: 4px; border: 1px solid black;")
			popup.setWindowFlags(Qt.ToolTip)
			popup.move(10, 10)
			popup.show()
			QTimer.singleShot(3000, lambda: popup.deleteLater())

			self.status_label.setText(f"Status: Downloading '{suggested}'...")
			try:
				download.finished.connect(lambda: self.status_label.setText(f"Status: Download finished: '{suggested}'"))
			except Exception:
				pass
		except Exception:
			pass

	# ------ bookmarks ------
	def load_bookmarks(self):
		if os.path.exists(BOOKMARK_FILE):
			try:
				with open(BOOKMARK_FILE, "r", encoding="utf-8") as f:
					return json.load(f)
			except Exception:
				return []
		return []

	def save_bookmarks(self):
		tmp = BOOKMARK_FILE + ".tmp"
		try:
			with open(tmp, "w", encoding="utf-8") as f:
				json.dump(self.bookmarks, f, indent=2)
			os.replace(tmp, BOOKMARK_FILE)
		except Exception:
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

		browser.setHtml("<h1>Welcome to openWeb!</h1><p>Type a URL above to surf.</p><p>Version 1.9 (clean)</p>")
		# title change handler
		browser.titleChanged.connect(
			lambda t, w=page: self.tabs.setTabText(self.tabs.indexOf(w), (t[:15] + ("..." if len(t) > 15 else "")) if t else "Tab")
		)
		# load finished handler updates status (one handler per browser)
		browser.loadFinished.connect(lambda ok, b=browser: self.check_load(ok, b))

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
			self._scroll_msg = "Viewing"

	def go_forward(self):
		b = self.current_browser()
		if b:
			b.forward()
			self._scroll_msg = "Viewing"

	def reload_page(self):
		b = self.current_browser()
		if b:
			b.reload()
			self._scroll_msg = "Reloading..."

	# --- SMART URL / SEARCH ---
	def start_loading(self):
		b = self.current_browser()
		if not b:
			return
		text = self.url_bar.text().strip()
		if not text:
			return

		# If it looks like a URL, ensure scheme; otherwise do a search
		is_probable_url = bool(re.search(r"\.[a-z]{2,}$", text)) and " " not in text
		if is_probable_url or text.startswith(("http://", "https://")):
			url = text
			if not url.startswith(("http://", "https://")):
				url = "https://" + url
			qurl = QUrl(url)
			host = qurl.host()
			# auto-add www for short hostnames if helpful
			if host and not host.startswith("www.") and "/" not in qurl.path() and host.count(".") <= 2:
				url = url.replace(host, "www." + host, 1)
		else:
			query = text.replace(" ", "+")
			url = f"https://www.google.com/search?q={query}"

		self.loading_url = QUrl(url)
		self._scroll_msg = "Loading..."
		try:
			b.load(self.loading_url)
		except Exception:
			self._scroll_msg = "Failed to Load..."

	def check_load(self, ok, browser=None):
		if not ok:
			self._scroll_msg = "Offline, check your internet."
		else:
			self._scroll_msg = "Viewing"

	def save_geometry(self):
		s = QSettings("openWeb", "browser")
		try:
			s.setValue("geometry", self.saveGeometry())
		except Exception:
			pass

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
				clear_cache.setText("Cache Clear Failed")

		def clear_cookies_action():
			try:
				profile.cookieStore().deleteAllCookies()
				clear_cookies.setText("Cookies Cleared!")
			except Exception:
				clear_cookies.setText("Cookie Clear Failed")

		def reset_all_action():
			try:
				try:
					profile.clearHttpCache()
					profile.cookieStore().deleteAllCookies()
				except Exception:
					pass

				targets = ["bookmarks.json", "session.json"]
				for filename in targets:
					path = os.path.join(APP_DATA_DIR, filename)
					if os.path.exists(path):
						try:
							os.remove(path)
						except Exception:
							pass

				# clear in-memory lists
				try:
					self.bookmarks.clear()
				except Exception:
					pass

				# attempt best-effort cleanup of styles/scripts injected into open pages
				try:
					for i in range(self.tabs.count()):
						page = self.tabs.widget(i)
						b = page.findChild(QWebEngineView) if page else None
						if b:
							js_remove = """
							try {
							  document.querySelectorAll('style, link[rel=stylesheet]').forEach(n=>{
								try {
								  const text = (n.innerText || n.href || '').toLowerCase();
								  if (text.includes('highlight') || text.includes('openweb') || text.includes('extension')) {
									n.remove();
								  }
								} catch(e){}
							  });
							} catch(e){}
							"""
							b.page().runJavaScript(js_remove)
							b.reload()
				except Exception:
					pass

				reset_all.setText("All Data Reset!")
			except Exception:
				reset_all.setText("Reset Failed")

		clear_cache.clicked.connect(clear_cache_action)
		clear_cookies.clicked.connect(clear_cookies_action)
		reset_all.clicked.connect(reset_all_action)

		dialog.setLayout(layout)
		dialog.exec_()

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
					pass

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

	def _scroll_status(self):
		if not hasattr(self, "_scroll_msg"):
			return
		text = self._scroll_msg
		if len(text) <= 30:
			self.status_label.setText("Status: " + text)
			return
		self._scroll_index = (self._scroll_index + 1) % len(text)
		view = text[self._scroll_index:] + "   " + text[:self._scroll_index]
		self.status_label.setText(view[:30])

	def stop_loading(self):
		b = self.current_browser()
		if b:
			b.stop()
			self._scroll_msg = "Stopped loading"

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
				def callback(_=None):
					try:
						vol = s.value() / 100.0
						js = f"document.querySelectorAll('video,audio').forEach(el => {{ try {{ el.volume = {vol}; }} catch(e) {{}} }});"
						b.page().runJavaScript(js)
					except Exception:
						pass
				return callback

			slider.valueChanged.connect(make_slider_callback())

			row = QHBoxLayout()
			row.addWidget(tab_label)
			row.addWidget(slider)
			layout.addLayout(row)

		dialog.setLayout(layout)
		dialog.exec_()

	# override close event to save session
	def closeEvent(self, event):
		try:
			self.save_session()
		except Exception:
			pass
		super().closeEvent(event)


# ---------- main ----------
def main():
	app = QApplication(sys.argv)
	window = OldInternetBrowser()
	window.show()
	sys.exit(app.exec_())


if __name__ == "__main__":
	main()
