"""
Qt tarafı: senkron motorunu arka planda çalıştıran işçi ve uzun süren ağ
çağrılarını arayüzü dondurmadan yapan yardımcı.
"""
import threading

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal

from cloud.firebase_client import ApiError, OfflineError


class SyncWorker(QThread):
    status_changed = Signal(object)  # SyncStatus

    def __init__(self, engine, interval=5.0, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.interval = interval
        self._wake = threading.Event()
        self._stop = threading.Event()

    def request_sync(self):
        """Bir işlem kuyruğa yazıldığında beklemeden senkron başlatır."""
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self.wait(15000)

    def run(self):
        while not self._stop.is_set():
            status = self.engine.run_once()
            self.status_changed.emit(status)
            if status.revoked:
                return
            # Kuyrukta iş varsa ya da internet yeni geldiyse daha sık dene.
            delay = 2.0 if status.pending and status.online else self.interval
            self._wake.wait(delay)
            self._wake.clear()


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, with_progress):
        super().__init__()
        self.fn = fn
        self.with_progress = with_progress
        self.signals = _TaskSignals()

    def run(self):
        try:
            if self.with_progress:
                result = self.fn(self.signals.progress.emit)
            else:
                result = self.fn()
            self.signals.done.emit(result)
        except OfflineError:
            self.signals.failed.emit('İnternet bağlantısı yok. Bu işlem için internet gerekir.')
        except ApiError as e:
            self.signals.failed.emit(e.message)
        except Exception as e:  # beklenmeyen hata kullanıcıya gösterilir, uygulama çökmez
            self.signals.failed.emit(f'Beklenmeyen hata: {e}')


_running = set()


def run_async(fn, on_done, on_failed, on_progress=None):
    """fn'i arka planda çalıştırır; sonuç Qt sinyaliyle ana thread'e döner."""
    task = _Task(fn, with_progress=on_progress is not None)
    task.setAutoDelete(False)
    _running.add(task)

    def finish(cb):
        def handler(value):
            _running.discard(task)
            cb(value)
        return handler

    task.signals.done.connect(finish(on_done))
    task.signals.failed.connect(finish(on_failed))
    if on_progress:
        task.signals.progress.connect(on_progress)
    QThreadPool.globalInstance().start(task)
    return task
