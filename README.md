Workup of the problem described at https://www.janestreet.com/bug-byte/

Approach:
* model graph using igraph
* set up constraints using cp sat solver from google ortools. use graph library to make it easy to set up the constraints
* there is one unique solution. use the weights computed from this solution to find the shortest path using igraph.
* transform weights of edges along shortest path into the corresponding letters to get the final answer.
