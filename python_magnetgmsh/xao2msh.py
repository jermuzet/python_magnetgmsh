"""
Retreive Physical Group from xao
Mesh using gmsh

TODO:
test with an xao file with embedded cad data (use stringio to cad)
retreive volume names from yaml file
link with MeshData
remove unneeded class like NumModel, freesteam, pint and SimMaterial

see gmsh/api/python examples for that
ex also in https://www.pygimli.org/_examples_auto/1_meshing/plot_cad_tutorial.html
"""
from typing import Type, Union

import os

import re
import argparse

import yaml

import gmsh


from .utils.files import load_Xao
from .mesh.groups import create_physicalbcs, create_physicalgroups
from .mesh.axi import get_allowed_algo as get_allowed_algo2D
from .mesh.axi import gmsh_msh
from .mesh.m3d import get_allowed_algo as get_allowed_algo3D


def main():
    tags = {}

    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("--debug", help="activate debug", action="store_true")
    parser.add_argument("--verbose", help="activate verbose", action="store_true")
    parser.add_argument("--env", help="load settings.env", action="store_true")
    parser.add_argument("--wd", help="set a working directory", type=str, default="")
    parser.add_argument(
        "--geo",
        help="specifiy geometry yaml file (use Auto to automatically retreive yaml filename fro xao, default is None)",
        type=str,
        default="None",
    )

    subparsers = parser.add_subparsers(
        title="commands", dest="command", help="sub-command help"
    )

    # parser_cfg = subparsers.add_parser('cfg', help='cfg help')
    parser_mesh = subparsers.add_parser("mesh", help="mesh help")
    parser_adapt = subparsers.add_parser("adapt", help="adapt help")

    parser_mesh.add_argument(
        "--algo2d",
        help="select an algorithm for 2d mesh",
        type=str,
        choices=get_allowed_algo2D(),
        default="Delaunay",
    )
    parser_mesh.add_argument(
        "--algo3d",
        help="select an algorithm for 3d mesh",
        type=str,
        choices=get_allowed_algo3D(),
        default="None",
    )
    parser_mesh.add_argument(
        "--lc",
        help="specify characteristic lengths (Magnet1, Magnet2, ..., Air (aka default))",
        type=float,
        nargs="+",
        metavar="LC",
    )
    parser_mesh.add_argument(
        "--scaling", help="scale to m (default unit is mm)", action="store_true"
    )
    parser_mesh.add_argument(
        "--dry-run",
        help="mimic mesh operation without actually meshing",
        action="store_true",
    )

    # TODO add similar option to salome HIFIMAGNET plugins
    parser_mesh.add_argument(
        "--group",
        help="group selected items in mesh generation (Eg Isolants, Leads, CoolingChannels)",
        nargs="+",
        metavar="BC",
        type=str,
    )
    parser_mesh.add_argument(
        "--hide",
        help="hide selected items in mesh generation (eg Isolants)",
        nargs="+",
        metavar="Domain",
        type=str,
    )

    parser_adapt.add_argument(
        "--bgm", help="specify a background mesh", type=str, default=None
    )
    parser_adapt.add_argument(
        "--estimator", help="specify an estimator (pos file)", type=str, default=None
    )

    args = parser.parse_args()
    if args.debug:
        print(args)

    cwd = os.getcwd()
    if args.wd:
        os.chdir(args.wd)

    hideIsolant = False
    groupIsolant = False
    groupLeads = False
    groupCoolingChannels = False

    is2D = False
    GeomParams = {"Solid": (3, "solids"), "Face": (2, "face")}

    # check if Axi is in input_file to see wether we are working with a 2D or 3D geometry
    if "Axi" in args.input_file:
        print("2D geometry detected")
        is2D = True
        GeomParams["Solid"] = (2, "faces")
        GeomParams["Face"] = (1, "edge")

    if args.command == "mesh":
        if args.hide:
            hideIsolant = "Isolants" in args.hide
        if args.group:
            groupIsolant = "Isolants" in args.group
            groupLeads = "Leads" in args.group
            groupCoolingChannels = "CoolingChannels" in args.group

    print("hideIsolant:", hideIsolant)
    print("groupIsolant:", groupIsolant)
    print("groupLeads:", groupLeads)
    print("groupCoolingChannels:", groupCoolingChannels)

    # init gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    # (0: silent except for fatal errors, 1: +errors, 2: +warnings, 3: +direct, 4: +information, 5: +status, 99: +debug)
    gmsh.option.setNumber("General.Verbosity", 0)
    if args.debug or args.verbose:
        gmsh.option.setNumber("General.Verbosity", 2)

    file = args.input_file  # r"HL-31_H1.xao"
    (gname, tree) = load_Xao(file, GeomParams, args.debug)

    # Loading yaml file to get infos on volumes
    cfgfile = ""
    solid_names = []
    bc_names = []

    innerLead_exist = False
    outerLead_exist = False
    NHelices = 0
    Channels = None

    if args.geo != "None":
        cfgfile = args.geo
    if args.geo == "Auto":
        cfgfile = gname + ".yaml"
    print("cfgfile:", cfgfile)

    from .cfg import loadcfg

    (solid_names, NHelices, Channels, lcs) = loadcfg(cfgfile, gname, is2D, args.verbose)

    if "Air" in args.input_file:
        solid_names.append("Air")
        if hideIsolant:
            raise Exception(
                "--hide Isolants cannot be used since cad contains Air region"
            )
        lcs["Air"] = 30

    nsolids = len(gmsh.model.getEntities(GeomParams["Solid"][0]))
    assert (
        len(solid_names) == nsolids
    ), f"Wrong number of solids: in yaml {len(solid_names)} in gmsh {nsolids}"

    print(f"NHelices = {NHelices}")
    print(f"Channels = {Channels}")

    # use yaml data to identify solids id...
    # Insert solids: H1_Cu, H1_Glue0, H1_Glue1, H2_Cu, ..., H14_Glue1, R1, R2, ..., R13, InnerLead, OuterLead, Air
    # HR: Cu, Kapton0, Kapton1, ... KaptonXX
    stags = create_physicalgroups(
        tree, solid_names, GeomParams, hideIsolant, groupIsolant, args.debug
    )

    # get groups
    bctags = create_physicalbcs(
        tree,
        GeomParams,
        NHelices,
        innerLead_exist,
        outerLead_exist,
        groupCoolingChannels,
        Channels,
        hideIsolant,
        groupIsolant,
        args.debug,
    )

    if args.command == "mesh" and not args.dry_run:

        if args.lc is None:
            print(f"Overwrite lcs def for MeshCarateristics")

        air = False
        if "Air" in args.input_file:
            air = True
        if is2D:
            gmsh_msh(args.alog2d, lcs, air, args.scaling)
        else:
            print("xao2msh: gmsh_msh for 3D not implemented")

        meshname = gname
        if is2D:
            meshname += "-Axi"
        if "Air" in args.input_file:
            meshname += "_withAir"
        print(f"Save mesh {meshname}.msh to {os.getcwd()}")
        gmsh.write(f"{meshname}.msh")

    if args.command == "adapt":
        print("adapt mesh not implemented yet")
    gmsh.finalize()
    return 0


if __name__ == "__main__":
    main()
