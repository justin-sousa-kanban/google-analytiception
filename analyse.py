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
parser.add_option('-s', '--sort', action='store', dest='field', default='views', help="Sort field to use (views, unique, percentage, time, avg_time)")
parser.add_option('-i', '--search', action='store', dest='search', help="Include only urls that match the given regular expression")
parser.add_option('-c', '--children', action='store', dest='children', type='int', help="Include only top x children for each node")
(options, args) = parser.parse_args()

class DataStore(defaultdict):
    def merge(self, other):
        for key in other:
            if other[key] == 0:
                continue
            if key == 'avg_time':
                self.add_avg(other, 'avg_time', 'views')
            elif key == 'avg_load':
                self.add_avg(other, 'avg_load', 'load_sample')
            else:
                self.add(other, key)

    def add(self, other, key):
        self[key] += other[key]

    def add_avg(self, other, key, denom):
        self[key] = (other[key] * other[denom] + self[key] * self[denom]) / (self[denom] + other[denom])


class TrackedItem(object):
    def __init__(self):
        self.name = ''
        self.parent = None
        self.data = DataStore(float)
        self.leaf = False
        self.node = Tree()

    @property
    def root(self):
        return self.parent.root if self.parent else self

    def update_stats(self, name, parent, data, sf):
        self.data.merge(data)
        self.name = self.node.name = name
        self.node.item = self
        if parent and self.node not in parent.node.children:
            self.parent = parent
            parent.node.add_child(self.node)

        self.node.add_feature("weight", self.data[sf])
        for key in self.data:
            self.node.add_feature(key, self.data[key])

    def __str__(self):
        return "%s: %s" % (self.name, ','.join(["%d %s" % (self.data[key], key) for key in self.data]))

class Path(TrackedItem):
    def __init__(self):
        super(Path, self).__init__()
        self.children = defaultdict(Path)
        self.parameters = defaultdict(Parameter)

    def full_path(self):
        return "%s/%s" % (self.parent.full_path(), self.name) if self.parent else ''

    def __str__(self):
        return "%s/%s" % (self.parent.full_path() if self.parent else '', super(Path, self).__str__())

    def print_data(self, depth=0, tab_size=4, sort_field='views', reverse=True):
        sort_function = lambda x: x.data[sort_field]
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

    def traverse(self, paths, parameters, data, sf):
        if len(paths) > 0:
            path = self.children[paths[0]]
            path.update_stats(paths[0], self, data, sf)
            path.traverse(paths[1:], parameters, data, sf)
        elif parameters:
            for key, val in parameters:
                parameter = self.parameters[key]
                parameter.update_stats(key, self, data, sf)
                value = parameter.values[val]
                value.update_stats(val, parameter, data, sf)
        #if self.name == 'acacia_technologies':
        #    ipdb.set_trace()
        if len(paths) is 0 or paths[0] == '':
            self.leaf = True

    def update(self, path, data, sf):
        if path.startswith('/'):
            if '?' in path:
                path, param_string = path.split('?', 1)
                parameters = map(lambda x: x.split('=', 1), param_string.split('&'))
                parameters = [p for p in parameters if len(p) is 2]
            else: 
                parameters = []
            paths = path.split('/')[1:]
            self.update_stats('', None, data, sf)
            self.traverse(paths, parameters, data, sf)

class Parameter(TrackedItem):
    def __init__(self):
        super(Parameter, self).__init__()
        self.values = defaultdict(Value)

    def full_path(self):
        return "%s?%s" % (self.parent.full_path(), self.name)

    def __str__(self):
        return "%s?%s" % (self.parent.full_path(), super(Parameter, self).__str__())

class Value(TrackedItem):
    def __init__(self):
        super(Value, self).__init__()

    def full_path(self):
        return "%s=%s" % (self.parent.full_path(), self.name)

    def __str__(self):
        return "%s=%s" % (self.parent.full_path(), super(Value, self).__str__())


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
        data = DataStore()
        if 'Pageviews' in row:
            data['views'] = int(row['Pageviews'].replace(',', ''))
        if 'Unique Pageviews' in row:
            data['unique'] = int(row['Unique Pageviews'].replace(',', ''))
        if 'Page Load Sample' in row:
            data['load_sample'] = int(row['Page Load Sample'].replace(',', ''))
        if 'Avg. Time on Page' in row:
            data['avg_time'] = to_seconds(row['Avg. Time on Page'])
        if 'Avg. Page Load Time (sec)' in row:
            data['avg_load'] = float(row['Avg. Page Load Time (sec)'])
        root.update(url, data, options.field)




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



