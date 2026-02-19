from imagingcontrol4.library import Library

from PyQt6.QtWidgets import QApplication

from mainwindow import MainWindow


def demoapp_main():
    with Library.init_context():
        argv = []
        app = QApplication(argv)
        app.setApplicationName("yt-control")
        app.setApplicationDisplayName("Yt Magnetometer Controller")
        app.setStyle("fusion")

        w = MainWindow()
        w.show()

        app.exec()


if __name__ == "__main__":
    demoapp_main()
