from gi.repository import Gtk, Gdk, GObject, GdkPixbuf, GtkSource, Pango
from threading import Thread
from etcd import Client
import os
import sys
import dbus


DIR = os.path.dirname(os.path.abspath(__file__))


def _load_pixbuf(path, size):
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(
        os.path.join(DIR, path),
        width=size, height=size,
        preserve_aspect_ratio=False
    )


class Async(object):
    def spawn(self, fn, result_cb):
        def wrapper():
            result = fn()
            Gdk.threads_add_idle(0, lambda: result_cb(result))
        Thread(target=wrapper).start()


class MainWindow(Gtk.Window, Async):
    # ICONS = {
    #     'dir': _load_pixbuf('icons/dir.png', 32),
    #     'file': _load_pixbuf('icons/file.png', 32)
    # }

    def __init__(self):
        super(MainWindow, self).__init__()

        self.last_notification_id = 0

        # if len(sys.argv) > 1:
        #     host, _, port = sys.argv[1].partition(':')
        #     if port:
        #         port = int(port)
        #     else:
        #         port = 2379
        # else:
        #     host, port = '127.0.0.1', 2379
        # print host, port
        # self.client = Client(host, port)

        self.client = None

        self.connect('destroy', Gtk.main_quit)

        self.set_title('gEtc')
        # self.window.set_icon_from_file(os.path.join(DIR, 'icons/icon128.png'))
        self.accels = Gtk.AccelGroup()

        self.tree_view = Gtk.TreeView()
        self.tree_model = Gtk.TreeStore(GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_STRING, GObject.TYPE_STRING)
        self.tree_view.set_model(self.tree_model)
        # self.tree_view.set_activate_on_single_click(True)
        self.tree_view.connect('row-expanded', self.row_expanded_cb)
        self.tree_view.connect('row-activated', self.row_activated_cb)
        self.tree_view.connect('button-press-event', self.show_context_menu)

        # Tree headers
        column = Gtk.TreeViewColumn('Item')
        renderer1 = Gtk.CellRendererPixbuf()
        renderer1.set_alignment(0, 0)
        column.pack_start(renderer1, expand=False)
        column.add_attribute(renderer1, 'icon_name', 3)
        renderer2 = Gtk.CellRendererText()
        column.pack_start(renderer2, expand=False)
        column.add_attribute(renderer2, 'text', 0)
        column.set_spacing(8)
        self.tree_view.append_column(column)

        self.tree_view.set_headers_visible(False)

        # Editor

        # self.doc_view = Gtk.TextView()
        self.notebook = Gtk.Notebook()
        self.notebook.set_show_tabs(True)
        self.notebook.set_tab_pos(Gtk.PositionType.TOP)

        self.ssm = GtkSource.StyleSchemeManager()
        self.ssm.append_search_path(os.path.join(DIR, 'styles'))
        self.lm = GtkSource.LanguageManager()

        # Layout

        self.box = Gtk.VBox()

        self.box.pack_start(self.create_toolbar(), False, True, 0)

        self.hbox = Gtk.HBox()

        self.hbox.pack_start(self.tree_view, False, True, 0)
        self.tree_view.set_size_request(200, -1)
        self.hbox.pack_start(self.notebook, True, True, 0)

        self.box.pack_start(self.hbox, True, True, 0)

        self.add(self.box)

        self.add_accel_group(self.accels)
        self.maximize()

        # Initial refresh

        # self.refresh()

    def _connect(self, button):
        result = self.prompt_hostname(self, 'Connect to host')
        if result:
            host, port = result
            self.client = Client(host, int(port))
            self.refresh()

    def create_toolbar(self):
        self.toolbar = Gtk.Toolbar()
        connect_button = Gtk.ToolButton.new_from_stock(Gtk.STOCK_CONNECT)
        connect_button.connect('clicked', self._connect)
        self.toolbar.insert(connect_button, 0)

        accelerator = '<Ctrl>o'
        key, mod = Gtk.accelerator_parse(accelerator)
        connect_button.add_accelerator('clicked', self.accels, key, mod, Gtk.AccelFlags.VISIBLE)

        self.toolbar.show_all()
        return self.toolbar

    def refresh(self):
        def process():
            self.tree_model.clear()
            try:
                result = self.client.get('/')
            except Exception as e:
                self.client = None
                self.notify('gtk-dialog-error', 'Error', 'Failed to connect:\n{}'.format(e.message))
                result = None
            return result
        self.spawn(process, self.refresh_cb)

    def refresh_cb(self, root):
        if not root:
            return
        iter = self.tree_model.append(None, ('/', '/', 'dir' if root.dir else 'doc', 'gtk-directory'))
        # self.tree_model.append(iter, ('Loading...', 'loading', 'gtk-refresh'))
        # self.populate(iter, root.children)
        self.set_empty(iter)

    # def populate(self, iter, children):
    #     for child in children:
    #         new_iter = self.tree_model.append(iter, (child.key, child.dir, 'gtk-directory' if child.dir else 'gtk-file'))
    #         # print len(list(child.children))
    #         # self.populate(new_iter, child.children)

    # def row_expanded_cb(self, tree_view, iter, path):
    #     child_iter = self.tree_model.iter_children(iter)
    #     while child_iter:
    #         child_iter.clear()
    #         child_iter = self.tree_model.iter_next(child_iter)

    def set_loading(self, iter):
        title_iter = self.tree_model.prepend(iter, ('Loading', None, 'loading', 'gtk-refresh'))
        other_iter = self.tree_model.iter_next(title_iter)
        if other_iter:
            while self.tree_model.remove(other_iter):
                pass

    def set_empty(self, iter):
        title_iter = self.tree_model.prepend(iter, ('Empty', None, 'empty', 'gtk-remove'))
        other_iter = self.tree_model.iter_next(title_iter)
        if other_iter:
            while self.tree_model.remove(other_iter):
                pass

    def set_ready(self, iter):
        child_iter = self.tree_model.iter_children(iter)
        while child_iter:
            is_loading_item = self.tree_model.get_value(child_iter, 2) == 'loading'
            if is_loading_item:
                if not self.tree_model.remove(child_iter):
                    child_iter = None
            else:
                child_iter = self.tree_model.iter_next(child_iter)

    def row_expanded_cb(self, tree_view, iter, path):
        # child_iter = self.tree_model.iter_children(iter)
            # child_iter = self.tree_model.iter_next(child_iter)
        # first_iter = self.tree_model.prepend(iter, ('Loading...', 'loading', 'gtk-refresh'))
        # first_iter = 
        # while self.tree_model.remove(child_iter):
        #     pass
        self.update(iter)

    def update(self, iter):
        self.set_loading(iter)

        def process():
            # self.tree_model.clear()
            path = self.tree_model.get_value(iter, 1)
            print 'Load', path
            return (iter, self.client.get(path))
        self.spawn(process, self.update_cb)

    def update_cb(self, data):
        iter, node = data
        has_children = False
        for child in node.children:
            if child.key == node.key:
                continue
            has_children = True
            child_iter = self.tree_model.append(iter, (os.path.basename(child.key), child.key, 'dir' if child.dir else 'doc', 'gtk-directory' if child.dir else 'gtk-file'))
            if child.dir:
                self.set_empty(child_iter)
            # self.tree_model.append(child_iter, ('Loading...', 'loading', 'gtk-refresh'))
        if not has_children:
            self.set_empty(iter)
        self.set_ready(iter)

    def row_activated_cb(self, tree_view, path, column):
        iter = self.tree_model.get_iter(path)
        node_type = self.tree_model.get_value(iter, 2)
        if node_type == 'doc':
            node_path = self.tree_model.get_value(iter, 1)
            self.new_editor(node_path)
        else:
            self.tree_view.expand_row(path, False)

    def new_editor(self, node_path):
        # Editor

        buff = GtkSource.Buffer()
        buff.set_language(self.lm.get_language('yaml'))
        buff.set_text(self.client.get(node_path).value)
        source = GtkSource.View.new_with_buffer(buff)
        source.set_show_line_numbers(True)
        source.set_highlight_current_line(True)
        source.set_tab_width(4)
        source.set_draw_spaces(
            GtkSource.DrawSpacesFlags.SPACE |
            GtkSource.DrawSpacesFlags.TAB |
            GtkSource.DrawSpacesFlags.LEADING |
            GtkSource.DrawSpacesFlags.TRAILING |
            GtkSource.DrawSpacesFlags.SPACE
        )
        source.set_insert_spaces_instead_of_tabs(True)
        source.set_auto_indent(True)

        font = Pango.FontDescription('Monospace')
        source.modify_font(font)

        buff.set_style_scheme(self.ssm.get_scheme('monokai-extended'))

        # Save Button

        def save_doc(button):
            self.client.set(node_path, buff.get_text(buff.get_start_iter(), buff.get_end_iter(), False))
            self.notify('gtk-save', 'Saved', 'Document with path {} was saved.'.format(node_path))

        save_button = Gtk.Button(
            'Save', valign=Gtk.Align.CENTER, halign=Gtk.Align.START, margin=5,
            image=Gtk.Image.new_from_icon_name('gtk-save', Gtk.IconSize.BUTTON)
        )
        save_button.connect('clicked', save_doc)
        save_button.set_always_show_image(True)
        save_button.set_relief(Gtk.ReliefStyle.NONE)

        # Close Button

        def close_doc(button):
            self.notebook.remove_page(self.notebook.get_current_page())

        close_button = Gtk.Button(
            'Close', valign=Gtk.Align.CENTER, halign=Gtk.Align.END, margin=5,
            image=Gtk.Image.new_from_icon_name('gtk-close', Gtk.IconSize.BUTTON)
        )
        close_button.connect('clicked', close_doc)
        close_button.set_always_show_image(True)
        close_button.set_relief(Gtk.ReliefStyle.NONE)

        # Layout

        header_bar = Gtk.HBox()
        header_bar.pack_start(save_button, False, True, 0)
        header_bar.pack_end(close_button, False, True, 0)

        layout = Gtk.VBox()
        layout.pack_start(header_bar, False, True, 0)
        layout.pack_start(source, True, True, 0)

        label = Gtk.Label(os.path.basename(node_path))
        self.notebook.append_page(layout, label)
        layout.show_all()

        self.notebook.set_current_page(-1)

    def show_context_menu(self, tree_view, event):
        if event.button == 3:
            result = tree_view.get_path_at_pos(int(event.x), int(event.y))

            if not result:
                return

            path, column, x, y = result

            if not path:
                return

            iter = self.tree_model.get_iter(path)

            node_path, node_type = self.tree_model.get_value(iter, 1), self.tree_model.get_value(iter, 2)

            tree_view.grab_focus()
            tree_view.set_cursor(path, column, 0)

            menu = Gtk.Menu()

            def delete_node(item):
                parent_iter = self.tree_model.iter_parent(iter)
                if parent_iter:
                    self.client.delete(node_path, recursive=True)
                    self.update(parent_iter)
                    self.notify('gtk-dialog-info', 'Deleted', 'Document with path {} was deleted.'.format(node_path))
                else:
                    # TODO(dunai): Show error
                    # print 'Cannot delete root node!'
                    self.notify('gtk-dialog-error', 'Error', 'Cannot delete root node!')

            def create_document(item, is_dir):
                value = self.prompt_value(self, 'Enter the name for new {}'.format('directory' if is_dir else 'document'), node_path.rstrip('/') + '/', 'Create new document')
                if value:
                    new_path = os.path.join(node_path, value)
                    try:
                        if is_dir:
                            self.client.write(new_path, None, dir=True)
                        else:
                            self.client.set(new_path, '')
                        self.update(iter)
                        self.notify('gtk-dialog-info', 'Created', '{} created at {}.'.format('Directory' if is_dir else 'Document', new_path))
                    except Exception as e:
                        self.notify('gtk-dialog-error', 'Error', 'Failed to create node at {}:\n{}'.format(new_path, e.message))

            if node_type == 'dir':
                item = Gtk.MenuItem('Create child document')
                item.connect('activate', lambda item: create_document(item, False))
                menu.append(item)
                item = Gtk.MenuItem('Create child directory')
                item.connect('activate', lambda item: create_document(item, True))
                menu.append(item)
                item = Gtk.MenuItem('Delete directory')
                item.connect('activate', delete_node)
                menu.append(item)
            elif node_type == 'doc':
                item = Gtk.MenuItem('Delete document')
                item.connect('activate', delete_node)
                menu.append(item)
            else:
                return

            menu.show_all()

            menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())

    def notify(self, icon, title, message, progress=None, timeout=0):
        bus = dbus.SessionBus()

        notif = bus.get_object(
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications"
        )
        notify_interface = dbus.Interface(notif, "org.freedesktop.Notifications")

        app_name = "GEtc"
        id_num_to_replace = self.last_notification_id
        # actions_list = dict(default='asd', Close='asdasd')
        actions_list = ''
        if progress:
            hint = dict(value=progress)
        else:
            hint = ''

        self.last_notification_id = notify_interface.Notify(
            app_name, id_num_to_replace,
            icon, title, message,
            actions_list, hint, timeout
        )

    def prompt_value(self, parent, message, prefix='', title='', default=''):
        # Returns user input as a string or None
        # If user does not input text it returns None, NOT AN EMPTY STRING.
        dialogWindow = Gtk.MessageDialog(
            parent,
            Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            Gtk.MessageType.QUESTION,
            Gtk.ButtonsType.OK_CANCEL,
            message
        )

        dialogWindow.set_title(title)

        dialogBox = dialogWindow.get_content_area()
        hBox = Gtk.HBox()
        userEntry = Gtk.Entry(margin=8)
        userEntry.set_text(default)
        # userEntry.set_visibility(False)
        # userEntry.set_invisible_char("*")
        if prefix:
            prefixLabel = Gtk.Label(prefix, margin=8)
            hBox.pack_start(prefixLabel, False, True, 0)
        hBox.pack_start(userEntry, True, True, 0)
        userEntry.set_size_request(250, 0)
        dialogBox.pack_end(hBox, False, False, 0)

        dialogWindow.show_all()
        response = dialogWindow.run()
        text = userEntry.get_text()
        dialogWindow.destroy()
        if (response == Gtk.ResponseType.OK) and (text != ''):
            return text
        else:
            return None

    def prompt_hostname(self, parent, message):
        # Returns user input as a string or None
        # If user does not input text it returns None, NOT AN EMPTY STRING.
        dialogWindow = Gtk.MessageDialog(
            parent,
            Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            Gtk.MessageType.QUESTION,
            Gtk.ButtonsType.OK_CANCEL,
            message
        )

        dialogWindow.set_title('Connect')

        dialogBox = dialogWindow.get_content_area()
        hBox = Gtk.HBox(margin=8)

        host = Gtk.Entry()
        host.set_text('127.0.0.1')
        host.set_size_request(150, 0)
        hBox.pack_start(host, True, True, 0)

        label = Gtk.Label(':')
        hBox.pack_start(label, False, True, 8)

        port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        port.set_value(2379)
        port.set_size_request(50, 0)
        hBox.pack_start(port, True, True, 0)

        dialogBox.pack_end(hBox, False, False, 0)

        dialogWindow.show_all()
        response = dialogWindow.run()
        host = host.get_text()
        port = port.get_text()
        dialogWindow.destroy()
        if (response == Gtk.ResponseType.OK) and (host != ''):
            return host, port
        else:
            return None


class Application(object):
    def __init__(self):
        self.window = MainWindow()
        self.window.show_all()

    def start(self):
        Gtk.main()


Application().start()
