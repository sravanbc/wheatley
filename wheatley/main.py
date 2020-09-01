#!/usr/bin/env python3

"""
The file containing the main function for the bot, as well as all the command line argument parsing
required to make the bot easily configurable.
"""

import argparse
import logging
import os
import sys

from wheatley.rhythm import RegressionRhythm, WaitForUserRhythm
from wheatley.tower import RingingRoomTower
from wheatley.bot import Bot
from wheatley.page_parser import get_load_balancing_url, TowerNotFoundError, InvalidURLError
from wheatley.parsing import parse_peal_speed, PealSpeedParseError, parse_call

from wheatley.row_generation import RowGenerator, ComplibCompositionGenerator
from wheatley.row_generation import MethodPlaceNotationGenerator
from wheatley.row_generation.complib_composition_generator import PrivateCompError, InvalidCompError
from wheatley.row_generation.method_place_notation_generator import MethodNotFoundError, \
                                                                    generator_from_special_title


def create_row_generator(args):
    """ Generates a row generator according to the given CLI arguments. """
    if "comp" in args and args.comp is not None:
        try:
            row_gen = ComplibCompositionGenerator(args.comp)
        except (PrivateCompError, InvalidCompError) as e:
            sys.exit(f"Bad value for '--comp': {e}")
    elif "method" in args:
        try:
            row_gen = generator_from_special_title(args.method) or \
                      MethodPlaceNotationGenerator(
                          args.method,
                          parse_call(args.bob),
                          parse_call(args.single)
                      )
        except MethodNotFoundError as e:
            sys.exit(f"Bad value for '--method': {e}")
    else:
        assert False, \
            "This shouldn't be possible because one of --method and --comp should always be defined"

    return row_gen


def create_rhythm(peal_speed, inertia, max_bells_in_dataset, handstroke_gap, use_wait):
    """ Generates a rhythm object according to the given CLI arguments. """
    regression = RegressionRhythm(
        inertia,
        handstroke_gap=handstroke_gap,
        peal_speed=peal_speed,
        max_bells_in_dataset=max_bells_in_dataset
    )

    if use_wait:
        return WaitForUserRhythm(regression)

    return regression


def get_version_number():
    """
    Try to read the file with the version number, if not print an error and set a poison value as the
    version.
    """
    try:
        version_file_path = os.path.join(os.path.split(__file__)[0], "version.txt")

        with open(version_file_path) as f:
            return f.read()
    except IOError:
        return "<NO VERSION FILE FOUND>"


def configure_logging():
    """ Sets up the logging for the bot. """
    logging.basicConfig(level=logging.WARNING)

    logging.getLogger(Bot.logger_name).setLevel(logging.INFO)
    logging.getLogger(RingingRoomTower.logger_name).setLevel(logging.INFO)
    logging.getLogger(RowGenerator.logger_name).setLevel(logging.INFO)
    logging.getLogger(RegressionRhythm.logger_name).setLevel(logging.INFO)
    logging.getLogger(WaitForUserRhythm.logger_name).setLevel(logging.INFO)


def server_main(override_args=None, stop_on_join_tower=False):
    """
    The main function of Wheatley when spawned by the Ringing Room server.
    This has many many fewer options than the standard `main` function, on the basis that this running mode
    is designed to take its parameters over SocketIO whilst running, rather than from the CLI args.
    """
    __version__ = get_version_number()

    parser = argparse.ArgumentParser(
        description="A bot to fill in bells during ringingroom.com practices (server mode)."
    )

    parser.add_argument(
        "room_id",
        type=int,
        help="The numerical ID of the tower to join, represented as a row on 9 bells, \
              e.g. 763451928."
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        help="The port of the SocketIO server (which must be hosted on localhost)."
    )

    # Misc arguments
    parser.add_argument(
        "--version",
        action="version",
        version=f"Wheatley v{__version__}"
    )

    # Parse arguments
    # `[1:]` is apparently needed, because sys.argv[0] is the working file of the Python interpreter
    # which `parser.parse_args` does not want to see as an argument
    args = parser.parse_args(sys.argv[1:] if override_args is None else override_args)

    # Run the program
    configure_logging()

    # Args that we are currently 'missing'
    use_up_down_in = True
    stop_at_rounds = True
    method_title = "Plain Bob Major"
    peal_speed = 180
    inertia = 0.5
    max_bells_in_dataset = 15
    handstroke_gap = 1
    use_wait = True

    try:
        tower_url = "http://127.0.0.1:" + str(args.port)
    except TowerNotFoundError:
        sys.exit("Specified tower not found.")

    tower = RingingRoomTower(args.room_id, tower_url)
    row_generator = generator_from_special_title(method_title) or \
                    MethodPlaceNotationGenerator(
                        method_title,
                        None,
                        None
                    )
    rhythm = create_rhythm(peal_speed, inertia, max_bells_in_dataset, handstroke_gap, use_wait)
    bot = Bot(tower, row_generator, use_up_down_in, stop_at_rounds, rhythm, user_name="Wheatley",
              server_mode=True)

    with tower:
        tower.wait_loaded()

        print("=== LOADED ===")

        if not stop_on_join_tower:
            bot.main_loop()


def main(override_args=None, stop_on_join_tower=False):
    """
    The main function of the bot.
    This parses the CLI arguments, creates the Rhythm, RowGenerator and Bot objects, then starts
    the bot's mainloop.

    The two optional arguments are used by the integration tester to give Wheatley artificial argument values
    (override_args) and make Wheatley exit with error code 0 on joining a tower so that hanging forever
    can be differentiated from Wheatley's normal behaviour of sitting in an infinite loop waiting for input.
    """
    # If the user adds 'server-mode' to the command, run the server-mode main function instead of this one,
    # and remove the 'server-mode' argument
    unparsed_args = override_args or sys.argv[1:]
    if len(unparsed_args) > 1 and unparsed_args[0] == "server-mode":
        del unparsed_args[0]
        server_main(unparsed_args, stop_on_join_tower)
        # The `server_main` function shouldn't return, but if it does somehow manage to do so return instead
        # of running the standard main function as well
        return

    __version__ = get_version_number()

    # PARSE THE ARGUMENTS

    parser = argparse.ArgumentParser(
        description="A bot to fill in bells during ringingroom.com practices"
    )

    # Tower arguments
    tower_group = parser.add_argument_group("Tower arguments")
    tower_group.add_argument(
        "room_id",
        type=int,
        help="The numerical ID of the tower to join, represented as a row on 9 bells, \
              e.g. 763451928."
    )
    tower_group.add_argument(
        "--url",
        default="https://ringingroom.com",
        type=str,
        help="The URL of the server to join (defaults to 'https://ringingroom.com')"
    )
    tower_group.add_argument(
        "--name",
        default=None,
        type=str,
        help="If set, then the bot will ring bells assigned to the given name. \
             When not set, the bot rings unassigned bells."
    )

    # Row generation arguments
    row_gen_group = parser.add_argument_group("Row generation arguments")

    # An mutual exclusion group to disallow specifying both a method *and* a CompLib comp
    comp_method_group = row_gen_group.add_mutually_exclusive_group(required=True)
    comp_method_group.add_argument(
        "-c", "--comp",
        type=int,
        help="The ID of the complib composition you want to ring"
    )
    comp_method_group.add_argument(
        "-m", "--method",
        type=str,
        help="The title of the method you want to ring"
    )

    row_gen_group.add_argument(
        "-b",
        "--bob",
        default="14",
        help='An override for what place notation(s) should be made when a `Bob` is called in \
              Ringing Room.  These will by default happen at the lead end.  Examples: "16" or \
              "0:16" => 6ths place lead end bob.  "-1:3" or "-1:3.1" => a Grandsire Bob.  "20: 70" \
              => a 70 bob taking effect 20 changes into a lead (the Half Lead for Surprise Royal). \
              "20:7/0:4" => a 70 bob 20 changes into a lead and a 14 bob at the lead end. \
              "3: 5/9: 5" => bobs in Stedman Triples.  Defaults to "14".'
    )
    row_gen_group.add_argument(
        "-n",
        "--single",
        default="1234",
        help='An override for what place notation(s) should be made when a `Single` is called in \
              Ringing Room.  These will by default happen at the lead end.  Examples: "1678" or \
              "0:1678" => 6ths place lead end single.  "-1:3.123" => a Grandsire Single. \
              "20: 7890" => a 7890 single taking effect 20 changes into a lead (the Half Lead for \
              Surprise Royal). "3: 567/9: 567" => singles in Stedman Triples.  Defaults to "1234".'
    )
    row_gen_group.add_argument(
        "-u", "--use-up-down-in",
        action="store_true",
        help="If set, then the Wheatley will automatically go into changes after two rounds have been \
              rung."
    )
    row_gen_group.add_argument(
        "-s", "--stop-at-rounds",
        action="store_true",
        help="If set, then Wheatley will stand his bells the first time rounds is reached."
    )
    row_gen_group.add_argument(
        "-H", "--handbell-style",
        action="store_true",
        help="If set, then Wheatley will ring 'handbell style', i.e. ringing two strokes of \
              rounds then straight into changes, and stopping at the first set of rounds. By \
              default, he will ring 'towerbell style', i.e. only taking instructions from the \
              ringing-room calls. This is equivalent to using the '-us' flags."
    )

    # Rhythm arguments
    rhythm_group = parser.add_argument_group("Rhythm arguments")
    rhythm_group.add_argument(
        "-k", "--keep-going",
        action="store_true",
        help="If set, Wheatley will not wait for users to ring - instead, he will push on with the \
              rhythm."
    )
    rhythm_group.add_argument(
        "-w", "--wait",
        action="store_true",
        help="Legacy parameter, which is now set by default. The previous default behaviour of not waiting \
              can be set with '-k'/'--keep-going'."
    )
    rhythm_group.add_argument(
        "-I", "--inertia",
        type=float,
        default=0.5,
        help="Overrides Wheatley's 'inertia' - now much Wheatley will take other ringers' positions \
              into account when deciding when to ring.  0.0 means he will cling as closely as \
              possible to the current rhythm, 1.0 means that he will completely ignore the other \
              ringers."
    )
    rhythm_group.add_argument(
        "-S", "--peal-speed",
        default="2h58",
        help="Sets the default speed that Wheatley will ring (assuming a peal of 5040 changes), \
              though this will usually be adjusted by Wheatley whilst ringing to keep with other \
              ringers.  Example formatting: '3h4' = '3h4m' = '3h04m' = '3h04' = '184m' = '184'. \
              Defaults to '2h58'."
    )
    rhythm_group.add_argument(
        "-G", "--handstroke-gap",
        type=float,
        default=1.0,
        help="Sets the handstroke gap as a factor of the space between two bells.  Defaults to \
              '1.0'."
    )
    rhythm_group.add_argument(
        "-X", "--max-bells-in-dataset",
        type=int,
        default=15,
        help="Sets the maximum number of bells that Wheatley will store to determine the current \
              ringing speed.  If you make this larger, then he will be more consistent but less \
              quick to respond to changes in rhythm.  Defaults to '15'.  Setting both this and \
              --inertia to a very small values could result in Wheatley ringing ridiculously \
              quickly."
    )

    # Misc arguments
    parser.add_argument(
        "--version",
        action="version",
        version=f"Wheatley v{__version__}"
    )

    # Parse arguments
    args = parser.parse_args(unparsed_args)

    # Deprecation warnings
    if args.wait:
        print("Deprecation warning: `--wait` has been replaced with `--keep-going`!")

    # Run the program
    configure_logging()

    try:
        tower_url = get_load_balancing_url(args.room_id, args.url)
    except TowerNotFoundError as e:
        sys.exit(f"Bad value for 'room_id': {e}")
    except InvalidURLError as e:
        sys.exit(f"Bad value for '--url': {e}")

    tower = RingingRoomTower(args.room_id, tower_url)
    row_generator = create_row_generator(args)

    try:
        peal_speed = parse_peal_speed(args.peal_speed)
    except PealSpeedParseError as e:
        sys.exit(f"{e}")

    rhythm = create_rhythm(peal_speed, args.inertia, args.max_bells_in_dataset, args.handstroke_gap,
                           not args.keep_going)
    bot = Bot(tower, row_generator, args.use_up_down_in or args.handbell_style,
              args.stop_at_rounds or args.handbell_style, rhythm, user_name=args.name)

    with tower:
        tower.wait_loaded()

        print("=== LOADED ===")

        if not stop_on_join_tower:
            bot.main_loop()


if __name__ == "__main__":
    main()
