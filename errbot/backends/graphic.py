import logging
import os
import re
import sys

import errbot
from errbot.backends.base import Message, ONLINE
from errbot.backends.text import TextBackend   # we use that as we emulate MUC there already
from errbot.rendering import xhtml


# Can't use __name__ because of Yapsy
log = logging.getLogger('errbot.backends.graphic')

try:
    from PySide import QtCore, QtGui, QtWebKit
    from PySide.QtGui import QCompleter
    from PySide.QtCore import Qt
except ImportError:
    log.exception("Could not start the graphical backend")
    log.fatal("""
    If you intend to use the graphical backend please install PySide:
    -> On debian-like systems
    sudo apt-get install python-software-properties
    sudo apt-get update
    sudo apt-get install python-pyside
    -> On Gentoo
    sudo emerge -av dev-python/pyside
    -> On Arch
    sudo pacman -S python-pyside
     -> Generic/virtual envs
    pip install PySide
    """)
    sys.exit(-1)


class CommandBox(QtGui.QPlainTextEdit, object):
    newCommand = QtCore.Signal(str)

    def reset_history(self):
        self.history_index = len(self.history)

    def __init__(self, history, commands, prefix):
        self.prefix = prefix
        self.history_index = 0
        self.history = history
        self.reset_history()
        super().__init__()

        # Autocompleter
        self.completer = None
        self.updateCompletion(commands)
        self.autocompleteStart = None

    def updateCompletion(self, commands):
        if self.completer:
            self.completer.activated.disconnect(self.onAutoComplete)
        self.completer = QCompleter([(self.prefix + name).replace('_', ' ', 1) for name in commands], self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setWidget(self)
        self.completer.activated.connect(self.onAutoComplete)

    def onAutoComplete(self, text):
        # Select the text from autocompleteStart until the current cursor
        cursor = self.textCursor()
        cursor.setPosition(0, cursor.KeepAnchor)
        # Replace it with the selected text
        cursor.insertText(text)
        self.autocompleteStart = None

    # noinspection PyStringFormat
    def keyPressEvent(self, *args, **kwargs):
        event = args[0]
        key = event.key()
        ctrl = event.modifiers() == QtCore.Qt.ControlModifier
        alt = event.modifiers() == QtCore.Qt.AltModifier

        # don't disturb the completer behavior
        if self.completer.popup().isVisible() and key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab, Qt.Key_Backtab):
            event.ignore()
            return

        if self.autocompleteStart is not None and not event.text().isalnum() and \
                not (key == Qt.Key_Backspace and self.textCursor().position() > self.autocompleteStart):
            self.completer.popup().hide()
            self.autocompleteStart = None

        if key == Qt.Key_Space and (ctrl or alt):
            # Pop-up the autocompleteList
            rect = self.cursorRect(self.textCursor())
            rect.setSize(QtCore.QSize(300, 500))
            self.autocompleteStart = self.textCursor().position()
            self.completer.complete(rect)  # The popup is positioned in the next if block

        if self.autocompleteStart:
            prefix = self.toPlainText()
            cur = self.textCursor()
            cur.setPosition(self.autocompleteStart)

            self.completer.setCompletionPrefix(prefix)
            # Select the first one of the matches
            self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))

        if key == Qt.Key_Up and (ctrl or alt):
            if self.history_index > 0:
                self.history_index -= 1
                self.setPlainText(self.BOT_PREFIX + '%s %s' % self.history[self.history_index])
                key.ignore()
                return
        elif key == Qt.Key_Down and (ctrl or alt):
            if self.history_index < len(self.history) - 1:
                self.history_index += 1
                self.setPlainText(self.BOT_PREFIX + '%s %s' % self.history[self.history_index])
                key.ignore()
                return
        elif key == QtCore.Qt.Key_Return and (ctrl or alt):
            self.newCommand.emit(self.toPlainText())
            self.reset_history()
        super().keyPressEvent(*args, **kwargs)


urlfinder = re.compile(r'http([^\.\s]+\.[^\.\s]*)+[^\.\s]{2,}')


def htmlify(text, receiving):
    return '<div class="%s">%s</div>' % ('receiving' if receiving else 'sending', text)


err_path = os.path.dirname(errbot.__file__)
icon_path = os.path.join(err_path, 'err.svg')
bg_path = os.path.join(err_path, 'err-bg.svg')
css_path = os.path.join(err_path, 'backends', 'style', 'style.css')
TOP = """
<html>
  <body style="background-image: url('file://%s');">
""" % bg_path
BOTTOM = "</body></html>"


class ChatApplication(QtGui.QApplication):
    newAnswer = QtCore.Signal(str)

    def __init__(self, bot):
        self.bot = bot
        super().__init__(sys.argv)
        self.mainW = QtGui.QWidget()
        self.mainW.setWindowTitle('Errbot')
        self.mainW.setWindowIcon(QtGui.QIcon(icon_path))
        vbox = QtGui.QVBoxLayout()
        help_label = QtGui.QLabel("CTRL+Space to autocomplete -- CTRL+Enter to send your message")
        self.input = CommandBox(bot.cmd_history, bot.all_commands, bot.bot_config.BOT_PREFIX)
        self.output = QtWebKit.QWebView()
        self.output.settings().setUserStyleSheetUrl(QtCore.QUrl.fromLocalFile(css_path))

        # init webpage
        self.buffer = ""
        self.update_webpage()

        # layout
        vbox.addWidget(self.output)
        vbox.addWidget(self.input)
        vbox.addWidget(help_label)
        self.mainW.setLayout(vbox)

        # setup web view to open liks in external browser
        self.output.page().setLinkDelegationPolicy(QtWebKit.QWebPage.DelegateAllLinks)

        # connect signals/slots
        self.output.page().mainFrame().contentsSizeChanged.connect(self.scroll_output_to_bottom)
        self.output.page().linkClicked.connect(QtGui.QDesktopServices.openUrl)
        self.input.newCommand.connect(lambda text: bot.send_command(text))
        self.newAnswer.connect(self.new_message)

        self.mainW.show()

    def new_message(self, text, receiving=True):
        self.buffer += htmlify(text, receiving)
        self.update_webpage()

    def update_webpage(self):
        self.output.setHtml(TOP + self.buffer + BOTTOM)

    def scroll_output_to_bottom(self):
        self.output.page().mainFrame().scroll(0, self.output.page().mainFrame().scrollBarMaximum(QtCore.Qt.Vertical))

    def update_commands(self, commands):
        self.input.updateCompletion(commands)


class GraphicBackend(TextBackend):
    def __init__(self, config):
        super().__init__(config)
        self.bot_identifier = self.build_identifier('Err')
        # create window and components
        self.md = xhtml()
        self.app = ChatApplication(self)

    def connect_callback(self):
        super().connect_callback()
        self.app.update_commands(self.all_commands)

    def send_command(self, text):
        self.app.new_message(text, False)
        msg = Message(text)
        msg.frm = self.build_identifier(self.bot_config.BOT_ADMINS[0])  # assume this is the admin talking
        msg.to = self.bot_identifier  # To me only
        self.callback_message(msg)
        # implements the mentions.
        mentioned = [self.build_identifier(word[1:]) for word in re.findall(r"@[\w']+", text)
                     if word.startswith('@')]
        if mentioned:
            self.callback_mention(msg, mentioned)

        self.app.input.clear()

    def build_message(self, text):
        msg = Message(text)
        msg.frm = self.bot_identifier
        return msg  # rebuild a pure html snippet to include directly in the console html

    def send_message(self, mess):
        if hasattr(mess, 'body') and mess.body and not mess.body.isspace():
            content = self.md.convert(mess.body)
            self.app.newAnswer.emit(content)

    def change_presence(self, status: str = ONLINE, message: str = '') -> None:
        pass

    def serve_forever(self):
        self.connect_callback()  # notify that the connection occured

        try:
            self.app.exec_()
        finally:
            self.disconnect_callback()
            self.shutdown()
            exit(0)

    @property
    def mode(self):
        return 'graphic'

    def prefix_groupchat_reply(self, message, identifier):
        super().prefix_groupchat_reply(message, identifier)
        message.body = '@{0} {1}'.format(identifier.nick, message.body)
