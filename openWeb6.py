# openWeb.py6

import sys, random, json, os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLineEdit, QToolBar, QAction,
    QTabWidget, QWidget, QVBoxLayout, QDialog, QPushButton, QLabel, QListWidget, QInputDialog
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile
from PyQt5.QtCore import QUrl, QTimer, Qt
import re
from PyQt5.QtCore import QUrl, QTimer, Qt, QSettings

import logging
from PyQt5.QtCore import QStandardPaths

logging.basicConfig(filename="openweb.log", level=logging.ERROR, format="%(asctime)s - %(message)s")

APP_DATA_DIR = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
if not os.path.exists(APP_DATA_DIR):
    os.makedirs(APP_DATA_DIR)
BOOKMARK_FILE = os.path.join(APP_DATA_DIR, "bookmarks.json")

# ---- Browser ----
class OldInternetBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("openWeb Browser")
        self.setGeometry(100, 100, 900, 700)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tabs)

        self.toolbar = QToolBar()
        self.addToolBar(self.toolbar)

        self.url_bar = QLineEdit()
        self.url_bar.returnPressed.connect(self.start_loading)
        self.toolbar.addWidget(self.url_bar)

        for label, slot in {
            "<-": self.go_back,
            "->": self.go_forward,
            "Reload": self.reload_page,
            "New Tab": self.new_tab,
            "Manager": self.open_manager,
            "Bookmarks": self.open_bookmarks
        }.items():
            act = QAction(label, self)
            act.triggered.connect(slot)
            self.toolbar.addAction(act)

        self.setStyleSheet("""
            QMainWindow { background:#c0c0c0; }
            QToolBar { background:#e0e0e0; }
            QLineEdit { font-family:Courier; font-size:12px; }
        """)

        self.status_label = QLabel("Status: Ready!!!!")
        self.status_label.setStyleSheet("background:#e0e0e0; font-family:Courier; font-size:12px;")
        self.statusBar().addWidget(self.status_label)

        self.bookmarks = self.load_bookmarks()
        self.new_tab()

        self.restoreGeometry(QSettings("openWeb", "browser").value("geometry", b""))
        self.tabs.currentChanged.connect(lambda _: self.save_geometry())


    def load_bookmarks(self):
        if os.path.exists(BOOKMARK_FILE):
            with open(BOOKMARK_FILE, "r") as f:
                try:
                    return json.load(f)
                except Exception as e:
                    logging.error(f"Error loading bookmarks: {e}")
                    return []

        return []

    def save_bookmarks(self):
        tmp = BOOKMARK_FILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(self.bookmarks, f, indent=2)
            os.replace(tmp, BOOKMARK_FILE)  # atomic swap
        except Exception as e:
            logging.error(f"Error saving bookmarks: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)


    def current_browser(self):
        page = self.tabs.currentWidget()
        return page.findChild(QWebEngineView) if page else None

    def new_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        browser = QWebEngineView()
        browser.setHtml("<h1>Welcome to openWeb!</h1><p>Type a URL above to surf.</p>")
        browser.titleChanged.connect(lambda t, w=page: self.tabs.setTabText(self.tabs.indexOf(w), t[:15] + ("..." if len(t) > 15 else "")))
        layout.addWidget(browser)
        self.tabs.addTab(page, f"Tab {self.tabs.count()+1}")
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
        if not b: return
        text = self.url_bar.text().strip()
        if not text: return

        # regex to detect domain-like input
        domain_pattern = re.compile(
        r"^(?:http[s]?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/.*)?$"
      )


        match = domain_pattern.match(text)
        if match:
            # detected a domain
            url = text
            if not url.startswith(("http://","https://")):
                url = "https://" + url
            # only add www if it seems necessary
            host = QUrl(url).host()
            path = match.group(2) or ""
            if not host.startswith("www.") and "/" not in path and host.count('.') <= 2:

                url = url.replace(host, "www." + host)

        else:
            # treat as search
            url = "https://www.google.com/search?q=" + text.replace(" ", "+")

        self.loading_url = QUrl(url)
        self.status_label.setText("Status: Loading...")
        try:
            try:
                b.loadFinished.disconnect()  # disconnect any previous connections
            except TypeError:
                pass
            b.loadFinished.connect(self.check_load)
            b.load(self.loading_url)
        except Exception as e:
            logging.error(f"Failed to load {url}: {e}")
            self.status_label.setText("Status: Failed to Load... :(")



    def check_load(self, ok):
        if not ok:
            self.status_label.setText("Status: Offline!")
        else:
            self.status_label.setText("Status: Viewing")

    def save_geometry(self):
        s = QSettings("openWeb", "browser")
        s.setValue("geometry", self.saveGeometry())


    # --- Manager ---
    def open_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("openWeb Manager")
        dialog.setGeometry(200,200,300,200)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Browser Data Controls (global)"))
        clear_cache = QPushButton("Clear Cache")
        clear_cookies = QPushButton("Clear Cookies")
        layout.addWidget(clear_cache)
        layout.addWidget(clear_cookies)
        profile = QWebEngineProfile.defaultProfile()
        clear_cache.clicked.connect(lambda: (profile.clearHttpCache(), clear_cache.setText("Cache Cleared!")))
        clear_cookies.clicked.connect(lambda: (profile.cookieStore().deleteAllCookies(), clear_cookies.setText("Cookies Cleared!")))
        dialog.setLayout(layout)
        dialog.exec_()

    # --- Bookmarks ---
    def open_bookmarks(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Bookmarks")
        dialog.setGeometry(250,250,400,400)
        layout = QVBoxLayout(dialog)
        list_widget = QListWidget()
        for bm in self.bookmarks:
            list_widget.addItem(f"{bm['title']} - {bm['url']}")
        layout.addWidget(list_widget)
        add_btn = QPushButton("Add Current Page")
        del_btn = QPushButton("Delete Selected")
        layout.addWidget(add_btn)
        layout.addWidget(del_btn)

        def add_bookmark():
            b = self.current_browser()
            if not b: return
            url = b.url().toString()
            title = url if url else "Untitled"
            self.bookmarks.append({"title":title,"url":url})
            self.save_bookmarks()
            list_widget.addItem(f"{title} - {url}")

        def del_bookmark():
            selected = list_widget.currentRow()
            if selected >= 0:
                list_widget.takeItem(selected)
                self.bookmarks.pop(selected)
                self.save_bookmarks()

        def open_selected():
            selected = list_widget.currentRow()
            if selected >=0:
                url = self.bookmarks[selected]["url"]
                self.url_bar.setText(url)
                self.start_loading()

        list_widget.itemDoubleClicked.connect(lambda _: open_selected())
        add_btn.clicked.connect(add_bookmark)
        del_btn.clicked.connect(del_bookmark)
        dialog.setLayout(layout)
        dialog.exec_()

app = QApplication(sys.argv)
window = OldInternetBrowser()
window.show()
sys.exit(app.exec_())
