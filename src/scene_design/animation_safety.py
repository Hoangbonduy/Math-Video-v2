"""Reject shared mutable Manim targets before rendering."""
import ast
from src.shared._workflow_store import WorkflowError


def validate_source(tree, resolve):
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and resolve(node.func)=='Succession':
            if any(isinstance(n,ast.Attribute) and n.attr=='animate'
                   for arg in node.args for n in ast.walk(arg)):
                raise WorkflowError('INVALID_SCENE_CODE',
                    f'Line {node.lineno}: do not prebuild .animate inside Succession. '
                    'Use consecutive self.play calls, MoveAlongPath, or explicit Transform '
                    'targets copied from cumulative intended states.')


def validate_animations(animations):
    seen=set()
    def visit(animation):
        children=getattr(animation,'animations',())
        if children:
            for child in children:visit(child)
        elif type(animation).__name__ in ('_MethodAnimation','_AnimationBuilder'):
            mob=animation.mobject
            family={id(p) for p in mob.get_family()}
            if seen & family:
                raise WorkflowError('INVALID_SCENE_CODE',
                    'Multiple prebuilt .animate targets share geometry in one play/composition; '
                    'use consecutive plays or explicit independent Transform targets.')
            seen.update(family)
    for animation in animations:visit(animation)
