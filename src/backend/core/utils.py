"""Root utils for the core application."""

import json

from configurations import values


class JSONValue(values.Value):
    """
    A custom value class based on django-configurations Value class that
    allows to load a JSON string and use it as a value.
    """

    def to_python(self, value):
        """
        Return the python representation of the JSON string.
        """
        return json.loads(value)


def flat_to_nested(flat_items_list):
    """
    Convert a flat list of items with depth and path information into a nested structure.

    Args:
        flat_items_list: List of dictionaries with keys: depth, path, title

    Returns:
        Nested dictionary structure with children arrays

    Raises:
        ValueError: If multiple root elements are found
    """
    if not flat_items_list:
        return {}

    # Sort by path to ensure proper nesting
    sorted_items = sorted(flat_items_list, key=lambda x: x["path"])

    # Find root items (depth 1)
    root_items = [item for item in sorted_items if item["depth"] == 1]

    if len(root_items) > 1:
        raise ValueError("Multiple root elements found")

    if not root_items:
        # If no depth 1 items, find the minimum depth and use those as roots
        min_depth = min(item["depth"] for item in sorted_items)
        root_items = [item for item in sorted_items if item["depth"] == min_depth]
        if len(root_items) > 1:
            raise ValueError("Multiple root elements found")

    if not root_items:
        return {}

    root = root_items[0].copy()
    root["children"] = []

    # Build the tree structure
    def add_children(parent_path, parent_depth):
        children = []
        for item in sorted_items:
            if item["depth"] == parent_depth + 1 and item["path"].startswith(
                parent_path + "."
            ):
                child = item.copy()
                child["children"] = add_children(item["path"], item["depth"])
                children.append(child)
        return children

    root["children"] = add_children(root["path"], root["depth"])

    return root
