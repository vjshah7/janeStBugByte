from ortools.sat.python import cp_model
import igraph as ig

# https://www.janestreet.com/bug-byte/
'''
Fill in the edge weights in the graph below with the numbers 1 through 24, using each number exactly once. Labeled 
nodes provide some additional constraints:

(white background) - The sum of all edges directly connected to this node is M.
(green background) - There exists a non-self-intersecting path starting from this node where N is the sum of the 
weights of the edges on that path. Multiple numbers indicate multiple paths that may overlap.

Once the graph is filled, find the shortest (weighted) path from  to  and convert it to letters (1=A, 2=B, 
etc.) to find a secret message.
'''


class SolutionPrinter(cp_model.CpSolverSolutionCallback):
    _g: ig.Graph

    def __init__(self, g: ig.Graph, variables):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._g = g.copy()
        self.__variables = variables
        self.__solution_count = 0

    def on_solution_callback(self):
        self.__solution_count += 1
        for v in self.__variables:
            print("{}: {}".format(v, self.Value(v)))

        print()

        # add the computed weights to the graph
        self._g.es["weight"] = list(self.Value(v) for v in self.__variables)

        # find the shortest path
        shortest_paths = self._g.get_shortest_paths(3, to=17, weights=self._g.es["weight"], output="epath")
        print("found {} shortest path(s)".format(len(shortest_paths)))
        output_str = ""
        if shortest_paths:
            for edge in shortest_paths[0]:
                output_str = output_str + chr(self._g.es[edge]["weight"] + 64)

        print("decoded msg: {}".format(output_str))

    def solution_count(self):
        return self.__solution_count


def find_paths(g: ig.Graph, node_id: int, maxlen: int, path: list = None) -> list:
    assert maxlen >= 0

    if path is None:
        path = [node_id]
    else:
        path = path + [node_id]

    if len(path) == maxlen:
        return [path]

    paths = [path]
    for child_node_id in g.neighbors(node_id):
        if child_node_id not in path:
            child_paths = find_paths(g, child_node_id, maxlen, path)
            for child_path in child_paths:
                paths.append(child_path)

    return paths


def dedup_paths(paths: list) -> list:
    path_set_list = list()
    rl = list()
    for path in paths:
        if len(path) > 1:
            path_set = set(path)
            if path_set not in path_set_list:
                rl.append(path)
                path_set_list.append(path_set)

    return rl

def get_path_edges(g: ig.Graph, path: list) -> list:
    assert len(path) >= 2
    edge_list = []
    for ii in range(len(path) - 1):
        edge_seq = g.es.select(_between=([path[ii]], [path[ii+1]]))
        assert len(edge_seq) == 1
        edge_list.append(edge_seq[0])
    return edge_list


def get_max_pathlen(target: int) -> int:
    # since each edge must have a unique positive integer weight, the most edges a path can have with a
    #  total path weight of <M> is the highest integer <n> for which sum(range(1,n+1)) <= M
    # since this is max number of edges, add one for the corresponding max number of nodes on the path
    # sums = list(sum(range(1, x + 1)) for x in range(1, 9))
    sums = [1, 3, 6, 10, 15, 21, 28, 36]
    # highest observed path constraint in the problem is 31, so this is enough
    return next(x for x in range(len(sums)) if sums[x] > target) + 1


def main():
    n_vertices = 18
    n_edges = 24
    edges = [(0, 1), (0, 2), (1, 3), (2, 3), (2, 7), (3, 8), (4, 7), (5, 9), (6, 8), (7, 9), (8, 9), (7, 10), (8, 11),
             (9, 10), (9, 11), (10, 13), (11, 14), (10, 12), (10, 15), (11, 16), (13, 15), (13, 16), (15, 17), (16, 17)]
    assert len(edges) == n_edges
    g = ig.Graph(n_vertices, edges)
    assert g.ecount() == n_edges
    assert g.vcount() == n_vertices
    g.vs['sum-constraint'] = [17, 3, -1, -1, -1, -1, -1, 54, 49, 60, 79, 75, -1, 29, -1, 39, 25, -1]
    g.vs['path-constraint'] = [[], [], [19, 23], [], [31], [6, 9, 16], [8], [], [], [], [], [], [], [], [], [], [], []]
    # g.vs['id'] = list(range(n_vertices))
    # g.es['id'] = list(range(n_edges))

    model = cp_model.CpModel()

    edge_weights = []
    for ii in range(24):
        edge_weights.append(model.NewIntVar(1, 24, "edge {}".format(ii)))

    # each weight 1-24 can only be used once
    model.AddAllDifferent(edge_weights)

    # some nodes have already been labeled
    model.Add(edge_weights[3] == 12)
    model.Add(edge_weights[12] == 20)
    model.Add(edge_weights[13] == 24)
    model.Add(edge_weights[18] == 7)

    # sum constraints - The sum of all edges directly connected to this node is <M>.
    for vertex in g.vs:
        target = vertex['sum-constraint']
        if target > 0:
            incident_edges = vertex.incident()
            incident_ews = list(edge_weights[x.index] for x in incident_edges)
            model.Add(sum(incident_ews) == target)
            # print("adding contraint: sum of {} == {}".format(incident_ews, target))

    # path constraints - There exists a non-self-intersecting path starting from this node where <N> is the sum of the
    # weights of the edges on that path. Multiple numbers indicate multiple paths that may overlap.

    # strategy - for each such node, for each target number, get the longest possible path length (e.g.
    # 19 < 1 + 2 + 3 + 4 + 5 + 6, so max path length is 5), then get the set of all possible non-intersecting paths
    # originating from the node with path length <= allowable max, then set up constraints so that at least one of
    # the sum of the weights of those paths is equal to the target.
    trigger_vars: dict[int, dict[int, list[cp_model.IntVar]]] = {}
    for vertex in g.vs:
        trigger_vars[vertex.index] = {}
        pcs = vertex['path-constraint']
        for pc in pcs:
            trigger_vars[vertex.index][pc] = []
            max_pathlen = get_max_pathlen(pc)
            candidate_paths = find_paths(g, vertex.index, max_pathlen)
            candidate_paths = dedup_paths(candidate_paths)

            # set up constraints... at least one of the sums of the weights of these candidate paths must be exactly
            # equal to the path constraint pc
            # transform list of paths (nodes) into list of edge lists
            el_list = list(get_path_edges(g, path) for path in candidate_paths)
            for ii in range(len(el_list)):
                el = el_list[ii]
                el_weights = list(edge_weights[x.index] for x in el)
                trigger_var = model.NewBoolVar("path {} of {} weight equal to target {} for node {}?"
                                               .format(ii, len(el_list), pc, vertex.index))
                model.Add(sum(el_weights) == pc).OnlyEnforceIf(trigger_var)
                trigger_vars[vertex.index][pc].append(trigger_var)
            model.AddBoolOr(trigger_vars[vertex.index][pc])

    solver = cp_model.CpSolver()
    printer = SolutionPrinter(g, edge_weights)
    solver.parameters.enumerate_all_solutions = True
    status = solver.Solve(model, printer)

    print("status: {}, num solutions: {}, time: {} ms"
          .format(solver.StatusName(status), printer.solution_count(), solver.WallTime()))


if __name__ == '__main__':
    main()
