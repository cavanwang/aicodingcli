'''AST Analyzer 单元测试（轻量验证）'''

import sys
import os

# 模拟 config.WORKSPACE_DIR = 当前目录
sys.path.insert(0, ".")

import config
config.WORKSPACE_DIR = os.getcwd()

from agent.ast_analyzer import find_definition_in_file, find_references_in_workspace


def test_find_definition():
    print("🔍 测试 find_definition_in_file...")

    # 测试 import 行
    res = find_definition_in_file("test_sample.py", 1, 0)
    print("  ✅ import os →", res)

    # 测试 def 行
    res = find_definition_in_file("test_sample.py", 4, 0)
    print("  ✅ def hello →", res)

    # 测试赋值行
    res = find_definition_in_file("test_sample.py", 7, 0)
    print("  ✅ x = 42 →", res)


def test_find_references():
    print("🔍 测试 find_references_in_workspace...")
    res = find_references_in_workspace("os")
    print("  ✅ os 引用 →", res)


if __name__ == "__main__":
    test_find_definition()
    print()
    test_find_references()
