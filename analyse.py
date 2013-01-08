from collections import defaultdict
from ete2 import Tree, TreeStyle, NodeStyle, faces, AttrFace, CircleFace
from optparse import OptionParser
import sys
import csv
import re
import math

parser = OptionParser()
parser.add_option('-f', '--file', action='store', dest='file', help="File to parse")
parser.add_option('-t', '--tree', action='store_true', dest='tree', help="Use tree viewer instead of printing")
parser.add_option('-x', '--threshold', action='store', dest='threshold', type='int', default=0, help="Minimum value of sort field to allow in tree")
parser.add_option('-r', '--reverse', action='store_true', dest='reverse', help="Order sort field highest to lowest")
parser.add_option('-s', '--sort', action='store', dest='field', default='views', help="Sort field to use (views, unique, time, avg_time)")
parser.add_option('-i', '--search', action='store', dest='search', help="Include only urls that match the given regular expression")
parser.add_option('-c', '--children', action='store', dest='children', type='int', help="Include only top x children for each node")
(options, args) = parser.parse_args()

class TrackedItem(object):
    def __init__(self):
        self.name = ''
        self.views = 0.0
        self.unique = 0.0
        self.avg_time = 0.0
        self.time = 0.0
        self.leaf = False
        self.node = Tree()

    def update_stats(self, name, parent_node, views, unique, time, avg_time, sf):
        self.avg_time = avg_time * views + self.avg_time * self.views
        self.views += views
        self.avg_time /= self.views
        self.unique += unique
        self.time += time
        self.name = self.node.name = name
        if parent_node and self.node not in parent_node.children:
            parent_node.add_child(self.node)
        self.node.add_feature("weight", getattr(self, sf))
        self.node.add_feature("views", self.views)
        self.node.add_feature("unique", self.unique)
        self.node.add_feature("time", self.time)
        self.node.add_feature("avg_time", self.avg_time)
        self.node.item = self

    def __str__(self):
        return "%s: %d views, %d unique, %ds time, %ds average time" % (self.name, self.views, self.unique, self.time, self.avg_time)

class Path(TrackedItem):
    def __init__(self):
        super(Path, self).__init__()
        self.parent = None
        self.children = defaultdict(Path)
        self.parameters = defaultdict(Parameter)

    def full_path(self):
        return "%s/%s" % (self.parent.full_path(), self.name) if self.parent else ''

    def __str__(self):
        return "%s/%s" % (self.parent.full_path() if self.parent else '', super(Path, self).__str__())

    def print_data(self, depth=0, tab_size=4, sort_field='views', reverse=True):
        sort_function = lambda x: getattr(x, sort_field)
        tab = ' ' * tab_size
        print "%s%s" % (tab * depth, self)
        if self.parameters:
            print "%sParameters:" % (tab * (depth + 1))
            for parameter in sorted(self.parameters.values(), key=sort_function, reverse=reverse):
                print "%s%s" % (tab * (depth + 2), parameter)
                for value in sorted(parameter.values.values(), key=sort_function, reverse=reverse):
                    print "%s%s" % (tab * (depth + 3), value)
        for child in sorted(self.children.values(), key=sort_function, reverse=reverse):
            child.print_data(depth + 1, tab_size, sort_field)

    def traverse(self, paths, parameters, views, unique, time, avg_time, sf):
        if len(paths) > 0:
            path = self.children[paths[0]]
            path.parent = self
            path.update_stats(paths[0], self.node, views, unique, time, avg_time, sf)
            path.traverse(paths[1:], parameters, views, unique, time, avg_time, sf)
        elif parameters:
            for key, val in parameters:
                parameter = self.parameters[key]
                parameter.update_stats(key, self.node, views, unique, time, avg_time, sf)
                value = parameter.values[val]
                value.update_stats(val, parameter.node, views, unique, time, avg_time, sf)
        #if self.name == 'acacia_technologies':
        #    ipdb.set_trace()
        if len(paths) is 0 or paths[0] == '':
            self.leaf = True

    def update(self, path, views, unique, time, avg_time, sf):
        if path.startswith('/'):
            if '?' in path:
                path, param_string = path.split('?', 1)
                parameters = map(lambda x: x.split('=', 1), param_string.split('&'))
                parameters = [p for p in parameters if len(p) is 2]
            else: 
                parameters = []
            paths = path.split('/')[1:]
            self.update_stats('', None, views, unique, time, avg_time, sf)
            self.traverse(paths, parameters, views, unique, time, avg_time, sf)

class Parameter(TrackedItem):
    def __init__(self):
        super(Parameter, self).__init__()
        self.values = defaultdict(Value)

class Value(TrackedItem):
    def __init__(self):
        super(Value, self).__init__()



# convert an "HH:MM:SS" string to an integer representing the total number of seconds
def to_seconds(time):
    return sum([x * (60 ** i) for i,x in enumerate(map(int, time.split(':')[::-1]))])

with open(options.file, 'r') as f:
    reader = csv.DictReader(f)
    root = Path()
    search = re.compile(options.search) if options.search else None
    for row in reader:
        url = row['Page']
        url = re.sub(r'(app/)+', 'app/', url)
        url = re.sub(r'^/https?://[\w\.]+/', '/', url)
        if search and not re.match(search, url):
            continue
        views = int(row['Pageviews'].replace(',', ''))
        unique = int(row['Unique Pageviews'].replace(',', ''))
        avg_time = to_seconds(row['Avg. Time on Page'])
        time = views * avg_time
        root.update(url, views, unique, time, avg_time, options.field)




if options.tree:
    weights = [math.log(node.weight + 1) for node in root.node.traverse()]
    mn = min(weights)
    mx = max(weights)
    adjust = lambda x: (100 * (math.log(x + 1) - mn) / (mx - mn)) + 1
    for node in root.node.traverse():
        if node.weight < options.threshold:
            node.detach()
        node.weight = adjust(node.weight)
    for node in root.node.traverse():
        node.children.sort(lambda x,y: cmp(x.weight, y.weight))
        if options.children:
            for child in node.children[:-options.children]:
                child.detach()

    def layout(node):
        def color(node):
            if type(node.item) is Value:
                return "Red"
            elif type(node.item) is Parameter:
                return "Yellow"
            elif node.item.leaf:
                return "Green"
            else:
                return "RoyalBlue"
        N = AttrFace("name", fsize=14, fgcolor="black")
        faces.add_face_to_node(N, node, 0)
        C = CircleFace(radius=node.weight, color=color(node), style="sphere")
        C.opacity = 0.3
        faces.add_face_to_node(C, node, 0, position="float")

    ts = TreeStyle()
    ts.layout_fn = layout
    ts.mode = "c"
    ts.show_leaf_name = False
    ts.force_topology = True
    root.node.show(tree_style=ts)
else:
    root.print_data(sort_field=options.field, reverse=options.reverse)



