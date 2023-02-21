#!/usr/bin/env python3
# encoding: UTF-8

"""defines Insert structure"""
from typing import List

import yaml
from python_magnetgeo.Insert import Insert

import gmsh
from .Helix import gmsh_ids as helix_ids
from .Helix import gmsh_bcs as helix_bcs
from .Ring import gmsh_ids as ring_ids
from .Ring import gmsh_bcs as ring_bcs


def flatten(S: list) -> list:
    from pandas.core.common import flatten as pd_flatten

    return list(pd_flatten(S))


def gmsh_ids(Insert: Insert, AirData: tuple, debug: bool = False) -> tuple:
    """
    create gmsh geometry
    """
    gmsh_ids = ()

    # loop over Helices
    z = []
    H_ids = []
    for i, name in enumerate(Insert.Helices):
        with open(f"{name}.yaml", "r") as f:
            Helix = yaml.load(f, Loader=yaml.FullLoader)

        _ids = helix_ids(Helix, (), debug)
        if i % 2 == 0:
            z.append(Helix.z[1])
        else:
            z.append(Helix.z[0])
        H_ids.append(_ids[0])

    # loop over Rings
    R_ids = []
    for i, name in enumerate(Insert.Rings):
        with open(f"{name}.yaml", "r") as f:
            Ring = yaml.load(f, Loader=yaml.FullLoader)

        y = z[i]
        if i % 2 != 0:
            y -= Ring.z[-1] - Ring.z[0]

        _id = ring_ids(Ring, y, debug)
        R_ids.append(_id)
        # fragment
        if i % 2 != 0:
            ov, ovv = gmsh.model.occ.fragment(
                [(2, _id)], [(2, H_ids[i][0]), (2, H_ids[i + 1][0])]
            )
        else:
            ov, ovv = gmsh.model.occ.fragment(
                [(2, _id)], [(2, H_ids[i][-1]), (2, H_ids[i + 1][-1])]
            )
        gmsh.model.occ.synchronize()

        if debug:
            print(
                f"Insert/Ring[{i}]: R_id={_id}, fragment produced volumes: {len(ov)}, {len(ovv)}"
            )
            for e in ov:
                print(e)

    # Now create air
    if AirData:
        (r, z) = Insert.boundingBox()
        # print(f"Insert: boundingbox= r={r}, z={z}")
        r0_air = 0
        dr_air = r[1] * AirData[0]
        z0_air = z[0] * AirData[1]
        dz_air = abs(z[1] - z[0]) * AirData[1]
        _id = gmsh.model.occ.addRectangle(r0_air, z0_air, 0, dr_air, dz_air)

        flat_list = flatten(H_ids)
        flat_list += R_ids

        """
        vGroups = [id[1] for id in gmsh.model.getEntities(2)]
        for i in flat_list:
            if not i in vGroups:
                raise RuntimeError(f"{i} is not in VGroups")
        """

        ov, ovv = gmsh.model.occ.fragment([(2, _id)], [(2, i) for i in flat_list])

        # need to account for changes
        gmsh.model.occ.synchronize()
        return (H_ids, R_ids, (_id, dr_air, z0_air, dz_air))

    # TODO return ids
    # need to account for changes
    gmsh.model.occ.synchronize()
    return (H_ids, R_ids, ())


def gmsh_bcs(Insert: Insert, mname: str, ids: tuple, debug: bool = False) -> dict:
    """
    retreive ids for bcs in gmsh geometry
    """
    import gmsh

    (H_ids, R_ids, AirData) = ids
    # print(f"Insert/gmsh_bcs: H_ids={H_ids}")

    eps = 1.0e-3
    defs = {}
    bcs_defs = {}

    prefix = ""
    if mname:
        prefix = f"{mname}_"

    # loop over Helices
    z = []
    H_Bc_ids = []
    NHelices = len(Insert.Helices)
    for i, name in enumerate(Insert.Helices):
        Helix = None
        with open(f"{name}.yaml", "r") as f:
            Helix = yaml.load(f, Loader=yaml.FullLoader)

        hdefs = helix_bcs(
            Helix, f"{prefix}H{i+1}", (H_ids[i], ()), debug
        )  # Helix.gmsh_bcs(hname, H_ids[i], debug)
        if i % 2 == 0:
            z.append(Helix.z[1])
        else:
            z.append(Helix.z[0])
        defs.update(hdefs)

        if i == 0:
            bcs_defs["H1_HP"] = [
                Helix.r[0] - eps,
                Helix.z[0] - eps,
                Helix.r[1] + eps,
                Helix.z[0] + eps,
            ]

    # loop over Rings
    R_Bc_ids = []
    NRings = len(Insert.Rings)
    for i, name in enumerate(Insert.Rings):
        Ring = None
        with open(f"{name}.yaml", "r") as f:
            Ring = yaml.load(f, Loader=yaml.FullLoader)

        y = z[i]
        if i % 2 != 0:
            y -= Ring.z[-1] - Ring.z[0]

        rdefs = ring_bcs(Ring, f"{prefix}R{i+1}", (i % 2 != 0), y, R_ids[i], debug)
        defs.update(rdefs)

    """
    # TODO group bcs by Channels
    num = 0
    NChannels = NHelices + 1
    for i in range(NChannels):
        print("Channel%d" % i)
        Channel_id = []
        if i == 0:
            # names.append("R%d_R0n" % (i+1)) # check Ring nummerotation
            Channel_id += R_Bc_ids[i][0]
        if i >= 1:
            # names.append("H%d_rExt" % (i))
            Channel_id += H_Bc_ids[i - 1][1]
        if i >= 2:
            # names.append("R%d_R1n" % (i-1))
            Channel_id += R_Bc_ids[i - 2][1]
        if i < NChannels:
            # names.append("H%d_rInt" % (i+1))
            if i < NHelices:
                Channel_id += H_Bc_ids[i][0]
            if i != 0 and i + 1 < NChannels:
                # names.append("R%d_CoolingSlits" % (i))
                print("R_Bc_ids[%d]" % i, R_Bc_ids[i - 1])
                Channel_id += R_Bc_ids[i - 1][2]
                # names.append("R%d_R0n" % (i+1))
                if i < NRings:
                    Channel_id += R_Bc_ids[i][0]

        ps = gmsh.model.addPhysicalGroup(1, Channel_id)
        gmsh.model.setPhysicalName(1, ps, "Channel%d" % i)
        defs["Channel%d" % i] = ps
    """

    if AirData:
        (Air_id, dr_air, z0_air, dz_air) = AirData

        ps = gmsh.model.addPhysicalGroup(2, [Air_id])
        gmsh.model.setPhysicalName(2, ps, "Air")
        defs["Air"] = ps
        # TODO: Axis, Inf
        gmsh.option.setNumber("Geometry.OCCBoundsUseStl", 1)

        eps = 1.0e-6

        bcs_defs[f"ZAxis"] = [-eps, z0_air - eps, +eps, z0_air + dz_air + eps]
        bcs_defs[f"Infty"] = [
            [-eps, z0_air - eps, dr_air + eps, z0_air + eps],
            [dr_air - eps, z0_air - eps, dr_air + eps, z0_air + dz_air + eps],
            [-eps, z0_air + dz_air - eps, dr_air + eps, z0_air + dz_air + eps],
        ]

    return defs
