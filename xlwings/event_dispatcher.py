import logging
import sys
import traceback

from . import Book, Sheet, Range
from . import xlplatform

import xlwings as xw
import win32api,win32con
                
_logger = logging.getLogger(__name__)


class EventDispatcher(object):

    _EVENT_NAMES = (
        # Workbook events
        'NewWorkbook', 'WorkbookOpen', 'WorkbookActivate', 'WorkbookNewSheet', 'WorkbookBeforeClose',
        'WorkbookBeforeSave', 'WorkbookAfterSave',
        # Sheet events
        'SheetActivate', 'SheetSelectionChange', 'SheetBeforeRightClick', 'SheetBeforeDoubleClick', 'SheetChange',
        # Internal events
        'AddinAfterLoad', 'AddinBeforeQuit')

    _ident_converter = lambda x: x
    _xl_workbook_converter = lambda xl_workbook: Book(impl=xlplatform.Book(xl_workbook))
    _xl_sheet_converter = lambda xl_sheet: Sheet(impl=xlplatform.Sheet(xl_sheet))
    _xl_range_converter = lambda xl_range: Range(impl=xlplatform.Range(xl_range))

    _PARGS_CONVERTERS = {
        # Workbook events
        'NewWorkbook': (_xl_workbook_converter, ),
        'WorkbookOpen': (_xl_workbook_converter, ),
        'WorkbookActivate': (_xl_workbook_converter, ),
        'WorkbookNewSheet': (_xl_workbook_converter, _xl_sheet_converter),
        'WorkbookBeforeClose': (_xl_workbook_converter, ),
        'WorkbookBeforeSave': (_xl_workbook_converter, _ident_converter),
        'WorkbookAfterSave': (_xl_workbook_converter, _ident_converter),
        # Sheet events
        'SheetActivate': (_xl_sheet_converter, ),
        'SheetSelectionChange': (_xl_sheet_converter, _xl_range_converter),
        'SheetBeforeRightClick': (_xl_sheet_converter, _xl_range_converter),
        'SheetBeforeDoubleClick': (_xl_sheet_converter, _xl_range_converter),
        'SheetChange': (_xl_sheet_converter, _xl_range_converter),
        # Internal events
        'AddinAfterLoad': (_ident_converter, ),
        'AddinBeforeQuit': (),
    }

    _event_callbacks = dict()

    @staticmethod
    def _default_exception_callback(event_name, callback_name, exc_type, exc, exc_tb):
        _logger.error(
            "Exception occured while processing user event '{}' by callback '{}', traceback follows:\n{}".format(
                event_name, callback_name, ''.join(traceback.format_exception(exc_type, exc, exc_tb))))

    _exception_callback = _default_exception_callback

    @classmethod
    def register_callback(cls, event_name, callback):
        """
        Register a callback for the given event. For more information on events, see:
         https://msdn.microsoft.com/en-us/library/office/dn254092.aspx
        event_name -- The event name to register the callback to.
        callback -- The callable to invoke when the given event fires. Variable signature depending on the event.
        """
        if event_name not in cls._EVENT_NAMES:
            raise Exception("Invalid event name '{}'".format(event_name))
        event_callbacks = cls._event_callbacks.setdefault(event_name, list())
        #win32api.MessageBox(xw.apps.active.api.Hwnd, str(len(event_callbacks)), 'Info', win32con.MB_ICONINFORMATION) 
        if callback not in event_callbacks:
            # _logger.debug("Registering callback {!r} for event name '{}'".format(callback, event_name))
            event_callbacks.append(callback)

    @classmethod
    def deregister_callback(cls, event_name, callback):
        """
        Deregister a callback for the given event. For more information on events, see:
         https://msdn.microsoft.com/en-us/library/office/dn254092.aspx
        event_name -- The event name to register the callback to.
        callback -- The callable to invoke when the given event fires. Variable signature depending on the event.
        """
        if event_name not in cls._EVENT_NAMES:
            raise Exception("Invalid event name '{}'".format(event_name))
        event_callbacks = cls._event_callbacks.get(event_name)
        if event_callbacks is None:
            return
        if callback in event_callbacks:
            # _logger.debug("Deregistering callback {!r} for event name '{}'".format(callback, event_name))
            event_callbacks.remove(callback)

    @classmethod
    def register_exception_callback(cls, callback):
        """
        Register a callback for processing exceptions occurred during event callbacks.
        callback -- The callable to invoke when an exception occurs. The signature is as follows:
         callback(event_name, callback_name, exc_type, exc, exc_tb)
        """
        # _logger.debug("Registering exception callback {!r}".format(callback))
        cls._exception_callback = staticmethod(callback)

    @classmethod
    def dispatch(cls, event_name, *pargs):
        parg_converters = cls._PARGS_CONVERTERS.get(event_name)
        if parg_converters is None:
            _logger.error('No conversors available to convert pargs for event {}'.format(event_name))
            return
        if len(parg_converters) != len(pargs):
            _logger.error('Conversors length differs from pargs length for event {}'.format(event_name))
            return
        args = [parg_converter(parg) for parg_converter, parg in zip(parg_converters, pargs)]
        for callback in cls._event_callbacks.get(event_name, set()):
            try:
                callback(*args)
            except Exception as ee:
                #win32api.MessageBox(xw.apps.active.api.Hwnd, 'Exception occurred during exception callback: {!s}'.format(ee), 'Info', win32con.MB_ICONINFORMATION) 
                if cls._exception_callback is not None:
                    try:
                        cls._exception_callback(event_name, callback.__name__, *sys.exc_info())
                    except Exception as e:
                        _logger.error('Exception occurred during exception callback: {!s}'.format(e))
                continue  # Ignore event exceptions


class EventHandler(type):
    """
    Class that represents an event handler. A class using this metaclass will register any method named as an event to
    the event dispatcher.

    .. note:: Usage: __metaclass__ = xlwings.EventHandler
    """

    def __init__(cls, name, bases, dct):
        super(EventHandler, cls).__init__(name, bases, dct)
        for event_name in EventDispatcher._EVENT_NAMES:
            callback = getattr(cls, event_name, None)
            if not callable(callback) or callback.__self__ is not cls:  # Only class methods
                continue
            EventDispatcher.register_callback(event_name, callback)
