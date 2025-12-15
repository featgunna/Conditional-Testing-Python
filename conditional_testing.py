import ast
import sys
from itertools import product
from types import FunctionType
import argparse
import pathlib
import shutil

covered_conditions = dict()

def add_branch(file_name, line_number, *args):
    key = (file_name, line_number)
    if key not in covered_conditions:
        covered_conditions[key] = set()
    covered_conditions[key].add(tuple(args))


class ASTParse(ast.NodeTransformer):
    def __init__(self, code_file):
        self.code_file = code_file
        self.condition_map = dict()
        self.function_names = set()

    def get_conditions(self, node):
        conditions = list()
        if isinstance(node, (ast.BoolOp, ast.UnaryOp)) and isinstance(node.op, (ast.And, ast.Or, ast.Not)):
            if isinstance(node, ast.UnaryOp):
                conditions.extend(self.get_conditions(node.operand))
            else:
                for val in node.values:
                    conditions.extend(self.get_conditions(val))
        else:
            conditions.append(node)
        return conditions

    def visit_FunctionDef(self, node):
        self.function_names.add(node.name)
        self.generic_visit(node)
        return node

    def visit_If(self, node):
        self.generic_visit(node)
        atomic_nodes = self.get_conditions(node.test)

        if not atomic_nodes:
            return node

        key = (self.code_file, node.lineno)
        self.condition_map[key] = [ast.unparse(ast_node).strip() for ast_node in atomic_nodes]

        tracker_args = [ast.Constant(value = self.code_file), ast.Constant(value = node.lineno), *atomic_nodes]

        tracker_call = ast.Expr(value = ast.Call(func = ast.Name(id = 'add_branch', ctx = ast.Load()), args = tracker_args, keywords=[]))

        return tracker_call, node


class CallParse(ast.NodeTransformer):
    def __init__(self, tested_functions):
        self.tested_functions = tested_functions

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in self.tested_functions:
            node.func.id = f"imported_{node.func.id}"
        return self.generic_visit(node)


class CallReroute(ast.NodeTransformer):
    def __init__(self, test_name, target_functions):
        self.test_name = test_name
        self.target_functions = target_functions
        self.assert_count = 0

    def visit_ImportFrom(self, node):
        if node.module == self.test_name:
            return None
        return node

    def visit_Assert(self, node):
        if not isinstance(node.test, ast.Compare):
            return node

        call_node = node.test.left

        if isinstance(call_node, ast.Call) and isinstance(call_node.func, ast.Name) and call_node.func.id in self.target_functions:
            self.assert_count += 1
            function_name = f"test_assert_{self.assert_count}"
            CallParse(self.target_functions).visit(call_node)

            assert_call = ast.FunctionDef(name = function_name,
                                              args = ast.arguments(posonlyargs = [], args = [], vararg = None, kwonlyargs = [], kw_defaults = [], kwarg = None, defaults = []),
                                              body = [ast.Expr(value = call_node)], decorator_list = [], returns = None)

            return assert_call

        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if str(node.name)[:5] == 'test_':
            CallParse(self.target_functions).visit(node)
            return node
        return self.generic_visit(node)


def loader(code_file):
    with open(code_file, 'r') as file:
        target_code = file.read()

    ast_tree = ast.parse(target_code, filename = code_file)

    ast_parser = ASTParse(code_file)
    processed_tree = ast_parser.visit(ast_tree)
    ast.fix_missing_locations(processed_tree)

    exec_scope = {'add_branch': add_branch, '__builtins__': globals()['__builtins__']}

    compiled_code = compile(processed_tree, code_file, 'exec')
    exec(compiled_code, exec_scope)

    return ast_parser, exec_scope


def tests_run(test_files, exec_scope, code_file):
    tested_functions = dict()
    for name in exec_scope:
        if isinstance(exec_scope[name], FunctionType):
            tested_functions[name] = exec_scope[name]

    if "add_branch" in tested_functions:
        del tested_functions["add_branch"]

    code_module = pathlib.Path(code_file).stem

    for test_file in test_files:
        try:
            with open(test_file, 'r') as file:
                test_code = file.read()

            test_tree = ast.parse(test_code, filename = test_file)

            router = CallReroute(code_module, tested_functions)
            processed_tree = router.visit(test_tree)
            ast.fix_missing_locations(processed_tree)

            compiled_code = compile(processed_tree, test_file, 'exec')

            test_globals = {'__builtins__': globals()['__builtins__']}

            for name, func in tested_functions.items():
                test_globals[f"imported_{name}"] = func

            exec(compiled_code, test_globals)

        except FileNotFoundError:
            print(f"Error: Provided file {test_file} cannot be found", file = sys.stderr)
            continue
        except AssertionError:
            print(f"Error: Assertion error in {test_file}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"Error: Execution of {test_file} failed: {e}", file = sys.stderr)
            continue

        to_test = list()
        for name, obj in test_globals.items():
            if str(name)[:5] == 'test_' and isinstance(obj, FunctionType):
                to_test.append((name, obj))

        if not to_test:
            print(f"Error: No test functions found in {test_file}")
            print("Warning: A test function should start with 'test_'")
            continue

        for test_name, test_func in to_test:
            try:
                test_func()
            except AssertionError:
                print(f"Error: Assertion error in {test_file}", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"Error: Test {test_name} in {test_file} failed: {e}", file = sys.stderr)
                sys.exit(1)


def testing_report(ast_parser):
    total_branches = 0
    total_covered_branches = 0
    terminal_width = shutil.get_terminal_size().columns

    print("=" * (terminal_width // 2 - 14) + " conditional tests coverage " + "=" * (terminal_width // 2 - 14))

    forks_count = len(ast_parser.condition_map)
    current_fork = 0

    for (filename, line), conditions in ast_parser.condition_map.items():
        current_fork += 1
        n = len(conditions)

        if n == 0:
            continue

        required_branches = 2 ** n

        covered_permutations = covered_conditions.get((filename, line), set())
        covered_branches = len(covered_permutations)

        total_branches += required_branches
        total_covered_branches += covered_branches

        possible_permutations = set(product([True, False], repeat = n))
        uncovered_permutations = possible_permutations - covered_permutations

        print(f"Conditional Branching in {filename} at line {line}:")
        print("")
        if len(conditions) <= 5:
            print(f"Conditions: {", ".join(conditions)}")
        else:
            print(f"Conditions: {", ".join(conditions[:5])} ...")
        print(f"Conditional Branch Count: {required_branches}")
        print(f"Covered Conditional Branches: {covered_branches}")

        if required_branches > 0:
            condition_score = (covered_branches / required_branches) * 100
        else:
            condition_score = 100

        print("")
        print(f"Local Score: {condition_score:.2f}%")

        if uncovered_permutations:
            print("")
            print(f"Uncovered Conditional Branch Count: {len(uncovered_permutations)}")
            if len(conditions) <= 5:
                if len(uncovered_permutations) <= 5:
                    for permutation in list(uncovered_permutations):
                        details = [f"{boolean} for {condition}" for boolean, condition in zip(permutation, conditions)]
                        print(f" - Missing: {', '.join(details)}")
                else:
                    for permutation in list(uncovered_permutations)[:5]:
                        details = [f"{boolean} for {condition}" for boolean, condition in zip(permutation, conditions)]
                        print(f" - Missing: {', '.join(details)}")
                    print("    ...   ")
            else:
                if len(uncovered_permutations) <= 5:
                    for permutation in list(uncovered_permutations):
                        details = [f"{boolean} for {condition}" for boolean, condition in zip(permutation[:5], conditions[:5])]
                        print(f" - Missing: {', '.join(details)} ...")
                else:
                    for permutation in list(uncovered_permutations)[:5]:
                        details = [f"{boolean} for {condition}" for boolean, condition in zip(permutation[:5], conditions[:5])]
                        print(f" - Missing: {', '.join(details)} ...")
                    print("    ...   ")


        if current_fork != forks_count:
            print("-" * ((terminal_width * 2) // 3))

    if total_branches == 0:
        overall_score = 100
    else:
        overall_score = (total_covered_branches / total_branches) * 100

    print("=" * (terminal_width // 2 - 14) + " conditional testing report " + "=" * (terminal_width // 2 - 14))
    print(f"Total Conditional Branches: {total_branches}")
    print(f"Total Covered Conditional Branches: {total_covered_branches}")
    print(f"Overall score: {overall_score:.2f}%")
    print("")


def loading_report(args):
    terminal_width = shutil.get_terminal_size().columns
    print("")
    print("=" * (terminal_width // 2 - 11) +" test session starts " + "=" * (terminal_width // 2 - 11))
    print(f"Code File: {args.code_file}")
    print(f"Test Files: {", ".join(set(args.test_files))}")


def main():
    if len(sys.argv) < 3:
        print("Wrong number of arguments!")
        print("Usage: python conditional_testing.py <code_file> <test_files>")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('code_file')
    parser.add_argument('test_files', nargs = '+')

    args = parser.parse_args()
    test_files = set(args.test_files)

    loading_report(args)

    try:
        ast_parser, exec_scope = loader(args.code_file)
        tests_run(test_files, exec_scope, code_file = args.code_file)
        testing_report(ast_parser)

    except FileNotFoundError as e:
        print(f"Error: Provided file not found: {e}", file = sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file = sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()