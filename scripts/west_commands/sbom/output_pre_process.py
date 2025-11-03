#
# Copyright (c) 2022 Nordic Semiconductor ASA
#
# SPDX-License-Identifier: LicenseRef-Nordic-5-Clause

'''
Pre-processing of data before it goes to the output.
'''

from data_structure import Data, License, LicenseExpr, Relationship
from license_utils import get_license, get_spdx_license_expr_info, is_spdx_license


def pre_process(data: Data):
    '''Do pre-processing of data for simpler usage by the output modules.'''
    # Sort files
    data.files.sort(key=lambda f: f.file_path)
    # Convert list of licenses to license expression for each file
    for file in data.files:
        licenses = file.licenses if len(file.licenses) > 0 else ['']
        simple_expr_items = set()
        or_expr_items = set()
        repeated_expr_items = set()
        for license in licenses:
            license = license.upper()
            info = get_spdx_license_expr_info(license)
            if info.valid and not info.is_id_only and len(info.licenses) > 1:
                repeated_expr_items.update(info.licenses)
            if not info.valid or info.or_present:
                or_expr_items.add(license)
            else:
                simple_expr_items.add(license)
        simple_expr_items -= repeated_expr_items
        if len(or_expr_items) > 1 or len(simple_expr_items) > 0:
            or_expr_items = { f'({x})' for x in or_expr_items }
        file.license_expr = ' AND '.join(sorted(simple_expr_items.union(or_expr_items)))
    # Collect all used detectors
    for file in data.files:
        data.detectors.update(file.detectors)
    # Collect all used licenses and license expressions and put them into data.licenses
    used_licenses = dict()
    for file in data.files:
        if file.license_expr in used_licenses:
            continue
        info = get_spdx_license_expr_info(file.license_expr)
        if not info.valid or not info.is_id_only:
            expr = LicenseExpr()
            expr.valid = info.valid
            expr.id = file.license_expr
            expr.friendly_id = info.friendly_expr
            expr.licenses = sorted(info.licenses)
            expr.custom = not info.valid
            for id in expr.licenses:
                if not is_spdx_license(id):
                    expr.custom = True
                    break
            used_licenses[file.license_expr] = expr
        for id in info.licenses:
            if id in used_licenses:
                continue
            elif is_spdx_license(id):
                used_licenses[id] = get_license(id)
            elif id in data.licenses:
                used_licenses[id] = data.licenses[id]
            else:
                lic = get_license(id)
                if lic is None:
                    lic = License()
                    lic.id = id
                    lic.friendly_id = id
                used_licenses[id] = lic
    data.licenses = used_licenses
    # Sort licenses
    def lic_reorder(id: str):
        lic = data.licenses[id]
        lic: 'License|LicenseExpr'
        if id == '':
            return 'A'
        elif lic.is_expr:
            if lic.custom:
                return 'B' + id
            else:
                return 'E' + id
        else:
            if id.startswith('LicenseRef-'):
                return 'D' + id
            elif lic.custom:
                return 'C' + id
            else:
                return 'F' + id
    data.licenses_sorted = sorted(data.licenses.keys(), key=lic_reorder)
    # Sort packages
    data.packages_sorted = sorted(data.packages.keys())
    # Assign SPDX identifiers to packages and files for stable cross references
    package_counter = 1
    for package_id in data.packages_sorted:
        package = data.packages[package_id]
        package.spdx_id = f'SPDXRef-Package-{package_counter}'
        package_counter += 1
        if package.external_refs is None:
            package.external_refs = list()
    file_counter = 1
    for file in data.files:
        file.spdx_id = f'SPDXRef-File-{file_counter}'
        file_counter += 1
    # Give more user friendly information of each package
    package_name_map = dict()
    for package in data.packages.values():
        if package.version is None:
            package.version = 'NoneVersion'
        if package.url is None:
            continue
        if (package.name is None) and ('github.com' in package.url):
            offs = package.url.find('github.com') + len('github.com') + 1
            package.name = package.url[offs:]
            if package.name.endswith('.git'):
                package.name = package.name[:-4]
        if package.name is None:
            package.name = package.id or package.url or 'NoneName'
        if package.name in package_name_map:
            existing = package_name_map[package.name]
            del package_name_map[package.name]
            package.name += '-' + package.version
            existing.name += '-' + existing.version
            package_name_map[existing.name] = existing
        package_name_map[package.name] = package
        if (package.browser_url is None) and (package.url.startswith('http')):
            package.browser_url = package.url
    # Ensure relationships list exists and describe packages from document
    def _should_keep_relationship(rel: Relationship) -> bool:
        if rel.spdx_id == 'SPDXRef-DOCUMENT' and rel.relationship_type == 'DESCRIBES':
            return False
        if rel.relationship_type == 'CONTAINS':
            return False
        return True
    if hasattr(data, 'relationships'):
        base_relationships = [rel for rel in data.relationships if _should_keep_relationship(rel)]
    else:
        base_relationships = list()
    data.relationships = base_relationships
    package_to_files = dict()
    for file in data.files:
        package_to_files.setdefault(file.package, list()).append(file.spdx_id)
    packages_with_files = set(package_to_files.keys())
    for package_id in data.packages_sorted:
        package = data.packages[package_id]
        if package.spdx_id and package_id in packages_with_files:
            relationship = Relationship()
            relationship.spdx_id = 'SPDXRef-DOCUMENT'
            relationship.relationship_type = 'DESCRIBES'
            relationship.related_spdx_id = package.spdx_id
            data.relationships.append(relationship)
    for package_id, file_ids in package_to_files.items():
        package = data.packages.get(package_id)
        if package is None or not package.spdx_id:
            continue
        for file_id in file_ids:
            contained_rel = Relationship()
            contained_rel.spdx_id = package.spdx_id
            contained_rel.relationship_type = 'CONTAINS'
            contained_rel.related_spdx_id = file_id
            data.relationships.append(contained_rel)
