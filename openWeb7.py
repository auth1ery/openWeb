# openWeb.py7

import sys, random, json, os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLineEdit, QToolBar, QAction,
    QTabWidget, QWidget, QVBoxLayout, QDialog, QPushButton, QLabel, QListWidget, QInputDialog
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile
from PyQt5.QtCore import QUrl, QTimer, Qt
import re
from PyQt5.QtCore import QUrl, QTimer, Qt, QSettings
from PyQt5.QtWebEngineWidgets import QWebEngineDownloadItem
from pathlib import Path
import logging
from PyQt5.QtCore import QStandardPaths
from pathlib import Path
import ntpath
from PyQt5.QtWidgets import QSlider, QHBoxLayout

logging.basicConfig(filename="openweb.log", level=logging.ERROR, format="%(asctime)s - %(message)s")

APP_DATA_DIR = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
if not os.path.exists(APP_DATA_DIR):
    os.makedirs(APP_DATA_DIR)
BOOKMARK_FILE = os.path.join(APP_DATA_DIR, "bookmarks.json")
SESSION_FILE = os.path.join(APP_DATA_DIR, "session.json")

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
            "Bookmarks": self.open_bookmarks,
            "Mixer": self.open_tab_mixer
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
        self.restore_session()

        self.restoreGeometry(QSettings("openWeb", "browser").value("geometry", b""))
        self.tabs.currentChanged.connect(lambda _: self.save_geometry())

    def save_session(self):
        print("Saving session...")  # debug
        session_data = []
        for i in range(self.tabs.count()):
            b = self.tabs.widget(i).findChild(QWebEngineView)
            if b:
                session_data.append(b.url().toString())
        try:
            with open(SESSION_FILE, "w") as f:
                json.dump(session_data, f, indent=2)
            print("Session saved")  # debug
        except Exception as e:
            logging.error(f"Error saving session: {e}")

    def restore_session(self):
        print("Restoring session...")  # debug
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r") as f:
                    urls = json.load(f)
                if urls:
                    self.tabs.clear()
                    for url in urls:
                        self.new_tab()
                        b = self.tabs.currentWidget().findChild(QWebEngineView)
                        if b:
                            b.load(QUrl(url))
                print("Session restored")  # debug
            except Exception as e:
                logging.error(f"Error restoring session: {e}")

    # ---- closeEvent override ----
    def closeEvent(self, event):
        print("App closing, saving session...")  # debug
        self.save_session()
        super().closeEvent(event)
    
    def setup_downloads(self, browser: QWebEngineView):
        browser.page().profile().downloadRequested.connect(self.handle_download)

    def handle_download(self, download):
        filename = ntpath.basename(download.path())  # works with spaces
        downloads_path = Path.home() / "Downloads" / filename
        download.setPath(str(downloads_path))
        download.accept()

        popup = QLabel(f"Downloading '{filename}'... Check the status at the bottom.", self)
        popup.setStyleSheet("background: yellow; color: black; padding: 4px; border: 1px solid black;")
        popup.setWindowFlags(Qt.ToolTip)  # makes it float like a toast
        popup.move(10, 10)
        popup.show()

        QTimer.singleShot(3000, lambda: popup.deleteLater())  # clean removal

        self.status_label.setText(f"Status: Downloading '{filename}'...")
        download.finished.connect(lambda: self.status_label.setText(f"Status: Download finished: '{filename}'"))

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
        self.setup_downloads(browser)
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
        
    def open_tab_mixer(self):
            dialog = QDialog(self)
            dialog.setWindowTitle("Tab Volume Mixer")
            dialog.setGeometry(300, 300, 350, 50 + 50 * self.tabs.count())
            layout = QVBoxLayout(dialog)

            for i in range(self.tabs.count()):
                page = self.tabs.widget(i)
                browser = page.findChild(QWebEngineView)
                if not browser: 
                    continue

                # Tab label
                tab_label = QLabel(self.tabs.tabText(i))
                tab_label.setFixedWidth(200)

                # Slider
                slider = QSlider(Qt.Horizontal)
                slider.setRange(0, 100)
                slider.setValue(100)  # full volume by default

                def make_slider_callback(b=browser, s=slider):
                    def callback():
                        vol = s.value()
                        # JS sets all video/audio elements' volume
                        js = f"document.querySelectorAll('video,audio').forEach(el => el.volume = {vol/100});"
                        b.page().runJavaScript(js)
                    return callback

                slider.valueChanged.connect(make_slider_callback())

                row = QHBoxLayout()
                row.addWidget(tab_label)
                row.addWidget(slider)
                layout.addLayout(row)

            dialog.setLayout(layout)
            dialog.exec_()

app = QApplication(sys.argv)
window = OldInternetBrowser()
window.show()
sys.exit(app.exec_())
