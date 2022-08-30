import datetime
import logging
import os
from pathlib import Path
from time import sleep

import click
import click_completion.core
import pandas as pd
import requests
from dacite.exceptions import MissingValueError
from git.exc import InvalidGitRepositoryError
from tqdm import tqdm

import colrev.cli_colors as colors
import colrev.exceptions as colrev_exceptions
import colrev.record
import colrev.review_manager

# pylint: disable=redefined-builtin
# pylint: disable=redefined-outer-name
# pylint: disable=too-many-arguments

# Note: autocompletion needs bash/... activation:
# https://click.palletsprojects.com/en/7.x/bashcomplete/


def __custom_startswith(string, incomplete):
    """A custom completion matching that supports case insensitive matching"""
    if os.environ.get("_CLICK_COMPLETION_COMMAND_CASE_INSENSITIVE_COMPLETE"):
        string = string.lower()
        incomplete = incomplete.lower()
    return string.startswith(incomplete)


click_completion.core.startswith = __custom_startswith
click_completion.init()


class SpecialHelpOrder(click.Group):
    def __init__(self, *args, **kwargs):
        self.help_priorities = {}
        super().__init__(*args, **kwargs)

    def get_help(self, ctx):
        self.list_commands = self.list_commands_for_help
        return super().get_help(ctx)

    def list_commands_for_help(self, ctx):
        """reorder the list of commands when listing the help"""
        commands = super().list_commands(ctx)
        return (
            c[1]
            for c in sorted(
                (self.help_priorities.get(command, 1), command) for command in commands
            )
        )

    def command(self, *args, **kwargs):
        """Behaves the same as `click.Group.command()` except capture
        a priority for listing command names in help.
        """
        help_priority = kwargs.pop("help_priority", 1)
        help_priorities = self.help_priorities

        def decorator(fun):
            # pylint: disable=super-with-arguments
            cmd = super(SpecialHelpOrder, self).command(*args, **kwargs)(fun)
            help_priorities[cmd.name] = help_priority
            return cmd

        return decorator


def get_value(msg: str, options: list) -> str:
    valid_response = False
    user_input = ""
    while not valid_response:
        print(f" {msg} (" + "|".join(options) + ")")
        user_input = input()
        if user_input in options:
            valid_response = True
    return user_input


@click.group(cls=SpecialHelpOrder)
@click.pass_context
def main(ctx):
    """CoLRev

    Main commands: init | status | search, load, screen, ...

    Documentation:  https://github.com/geritwagner/colrev/docs
    """


@main.command(help_priority=1)
@click.option("-n", "--name", help="Name of the repository (project)")
@click.option(
    "--type",
    type=str,
    default="literature_review",
    help="Review type (e.g., literature_review (default), curated_masterdata, realtime)",
)
@click.option("--url", help="Git remote URL (optional)")
@click.option(
    "--example",
    is_flag=True,
    default=False,
    help="Create example repository",
)
@click.pass_context
def init(ctx, name, type, url, example) -> bool:
    """Initialize repository"""
    import colrev.init

    try:
        # We check this again when calling init.initialize_repo()
        # but at this point, we want to avoid that users enter a lot of data and
        # see an error at the end

        cur_content = [str(x) for x in Path.cwd().glob("**/*")]

        # pylint: disable=duplicate-code
        if "venv" in cur_content:
            cur_content.remove("venv")
            # Note: we can use paths directly when initiating the project
        if "report.log" in cur_content:
            cur_content.remove("report.log")

        if 0 != len(cur_content):
            print("Empty directory required.")
            return False

        # Set reasonable defaults
        share_stat_req = "PROCESSED"

        colrev.init.Initializer(
            project_name=name,
            share_stat_req=share_stat_req,
            review_type=type,
            url=url,
            example=example,
        )

    except colrev_exceptions.ParameterError as exc:
        print(exc)

    return True


def print_review_instructions(review_instructions: dict) -> None:

    print("Review project\n")

    verbose = False

    key_list = [list(x.keys()) for x in review_instructions]
    keys = [item for sublist in key_list for item in sublist]
    priority_item_set = "priority" in keys

    for review_instruction in review_instructions:
        if priority_item_set and "priority" not in review_instruction.keys():
            continue
        if "info" in review_instruction:
            print("  " + review_instruction["info"])
        if "msg" in review_instruction:
            if "cmd" in review_instruction:
                if verbose:
                    print("  " + review_instruction["msg"] + ", i.e., use ")
                print(f'  {colors.ORANGE}{review_instruction["cmd"]}{colors.END}')
            else:
                print(f"  {colors.ORANGE}{review_instruction['msg']}{colors.END}")
        if "cmd_after" in review_instruction:
            print("  Then use " + review_instruction["cmd_after"])
        print()


def print_collaboration_instructions(collaboration_instructions: dict) -> None:

    print("Versioning and collaboration\n")

    if "status" in collaboration_instructions:
        if "title" in collaboration_instructions["status"]:
            title = collaboration_instructions["status"]["title"]
            if "WARNING" == collaboration_instructions["status"].get("level", "NA"):
                print(f"  {colors.RED}{title}{colors.END}")
            elif "SUCCESS" == collaboration_instructions["status"].get("level", "NA"):
                print(f"  {colors.GREEN}{title}{colors.END}")
            else:
                print("  " + title)
        if "msg" in collaboration_instructions["status"]:
            print(f'  {collaboration_instructions["status"]["msg"]}')

    for item in collaboration_instructions["items"]:
        if "title" in item:
            if "level" in item:
                if "WARNING" == item["level"]:
                    print(f'  {colors.RED}{item["title"]}{colors.END}')
                elif "SUCCESS" == item["level"]:
                    print(f'  {colors.GREEN}{item["title"]}{colors.END}')
            else:
                print("  " + item["title"])

        if "msg" in item:
            print("  " + item["msg"])
        if "cmd_after" in item:
            print(f'  {item["cmd_after"]}')
        print()


def print_environment_instructions(environment_instructions: dict) -> None:
    if len(environment_instructions) == 0:
        return

    print("CoLRev environment\n")

    key_list = [list(x.keys()) for x in environment_instructions]
    keys = [item for sublist in key_list for item in sublist]
    priority_item_set = "priority" in keys

    for environment_instruction in environment_instructions:
        if priority_item_set and "priority" not in environment_instruction.keys():
            continue
        if "info" in environment_instruction:
            print("  " + environment_instruction["info"])
        if "msg" in environment_instruction:
            if "cmd" in environment_instruction:
                print("  " + environment_instruction["msg"] + "  i.e., use ")
                print(f'  {colors.ORANGE}{environment_instruction["cmd"]}{colors.END}')
            else:
                print("  " + environment_instruction["msg"])
        if "cmd_after" in environment_instruction:
            print("  Then use " + environment_instruction["cmd_after"])
        print()


def print_progress(stat: dict) -> None:
    # Prints the percentage of atomic processing tasks that have been completed
    # possible extension: estimate the number of manual tasks (making assumptions on
    # frequencies of man-prep, ...)?

    total_atomic_steps = stat["atomic_steps"]
    completed_steps = stat["completed_atomic_steps"]

    if total_atomic_steps != 0:
        current = int((completed_steps / total_atomic_steps) * 100)
    else:
        current = -1

    sleep_interval = 1.1 / max(current, 100)
    print()

    for i in tqdm(
        range(100),
        desc="  Progress:",
        bar_format="{desc} |{bar}|{percentage:.0f}%",
        ncols=40,
    ):
        sleep(sleep_interval)
        if current in [i, -1]:
            break


def print_project_status(status_operation) -> None:
    import colrev.data

    stat = status_operation.review_manager.get_status_freq()
    try:
        # if ret_check["status"] + ret_f["status"] == 0:
        status_operation.review_manager.print_review_status(status_info=stat)
        print_progress(stat)
    except Exception as exc:
        print(f"Status failed ({exc})")

    print("")

    instructions = status_operation.get_instructions(stat=stat)
    print_review_instructions(instructions["review_instructions"])
    print_collaboration_instructions(instructions["collaboration_instructions"])
    print_environment_instructions(instructions["environment_instructions"])

    print("Checks\n")

    try:
        ret_check = status_operation.review_manager.check_repo(
            DATA=colrev.data.Data(
                review_manager=status_operation.review_manager,
                notify_state_transition_process=False,
            )
        )
    except colrev_exceptions.RepoSetupError as exc:
        ret_check = {"status": 1, "msg": exc}

    if 0 == ret_check["status"]:
        print(
            "  ReviewManager.check_repo()  ...  "
            f'{colors.GREEN}{ret_check["msg"]}{colors.END}'
        )
    if 1 == ret_check["status"]:
        print(f"  ReviewManager.check_repo()  ...  {colors.RED}FAIL{colors.END}")
        print(f'{ret_check["msg"]}\n')
        return

    try:
        ret_f = status_operation.review_manager.format_records_file()
    except KeyError as exc:
        print(exc)
        ret_f = {"status": 1, "msg": "KeyError"}
    if 0 == ret_f["status"]:
        print(
            "  ReviewManager.format()      ...  "
            f'{colors.GREEN}{ret_f["msg"]}{colors.END}'
        )
    if 1 == ret_f["status"]:
        print(f"  ReviewManager.format()      ...  {colors.RED}FAIL{colors.END}")
        print(f'\n    {ret_f["msg"]}\n')
    if not status_operation.review_manager.in_virtualenv():
        print(
            f"  {colors.RED}WARNING{colors.END} running scripts outside of virtualenv"
        )
        print(
            "  For instructions to set up a virtual environment, run\n"
            f"  {colors.ORANGE}colrev show venv{colors.END}"
        )
    print()


@main.command(help_priority=2)
@click.option(
    "-a",
    "--analytics",
    is_flag=True,
    default=False,
    help="Print analytics",
)
@click.pass_context
def status(ctx, analytics) -> None:
    """Show status"""
    import colrev.status

    if analytics:

        review_manager = colrev.review_manager.ReviewManager()
        status_operation = colrev.status.Status(review_manager=review_manager)
        analytic_results = status_operation.get_analytics()

        for cid, data_item in reversed(analytic_results.items()):
            print(f"{cid} - {data_item}")
        return

    try:

        review_manager = colrev.review_manager.ReviewManager()
        status_operation = colrev.status.Status(review_manager=review_manager)

        print_project_status(status_operation)

    except InvalidGitRepositoryError:
        print("Not a CoLRev/git repository. Run")
        print("    colrev init")
        return
    except colrev_exceptions.CoLRevUpgradeError as exc:
        print(exc)
        return
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
    except KeyboardInterrupt:
        print("Stopped...")


@main.command(help_priority=3)
@click.option(
    "-a",
    "--add",
    type=str,
    help="""
Format: RETRIEVE * FROM crossref WHERE title LIKE '%keyword%'
""",
)
@click.option("-v", "--view", is_flag=True, default=False, help="View search sources")
@click.option(
    "-s",
    "--selected",
    type=str,
    help="Only retrieve search results for selected sources",
)
@click.option(
    "-scs",
    "--setup_custom_script",
    is_flag=True,
    default=False,
    help="Setup template for custom search script.",
)
@click.option(
    "-f",
    "--force_mode",
    is_flag=True,
    default=False,
    help="Force mode: conduct full search again",
)
@click.pass_context
def search(ctx, add, view, selected, setup_custom_script, force_mode) -> None:
    """Retrieve search records"""
    import colrev.search

    try:
        review_manager = colrev.review_manager.ReviewManager(force_mode=force_mode)

        search_operation = colrev.search.Search(review_manager=review_manager)
        if add:
            search_operation.add_source(query=add)
        elif view:
            search_operation.view_sources()
        elif setup_custom_script:
            search_operation.setup_custom_script()
            print("Activated custom_search_script.py.")
            print("Please update the source in settings.json and commit.")
        else:
            search_operation.main(selection_str=selected)

    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
    except colrev_exceptions.NoSearchFeedRegistered as exc:
        print(exc)
    except colrev_exceptions.ServiceNotAvailableException as exc:
        print(exc)


@main.command(help_priority=4)
@click.option(
    "-k",
    "--keep_ids",
    is_flag=True,
    default=False,
    help="Do not change the record IDs. Useful when importing an existing sample.",
)
@click.option(
    "-c",
    "--combine_commits",
    is_flag=True,
    default=False,
    help="Combine load of multiple sources in one commit.",
)
@click.pass_context
def load(ctx, keep_ids, combine_commits) -> None:
    """Import records"""

    import colrev.load

    try:
        review_manager = colrev.review_manager.ReviewManager()
        # already start LocalIndex (for set_ids)
        review_manager.get_local_index(startup_without_waiting=True)
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        load_operation = colrev.load.Loader(review_manager=review_manager)
        load_operation.check_update_sources()
        if combine_commits:
            logging.info(
                "Combine mode: all search sources will be loaded in one commit"
            )
        # Note : reinitialize to load new scripts:
        load_operation = colrev.load.Loader(
            review_manager=load_operation.review_manager
        )
        load_operation.main(keep_ids=keep_ids, combine_commits=combine_commits)
    except colrev_exceptions.SearchSettingsError as exc:
        logging.error(f"SearchSettingsError: {exc}")


@main.command(help_priority=5)
@click.option(
    "--similarity",
    default=0.9,
    type=float,
    help="Retrieval similarity threshold",
)
@click.option(
    "-k",
    "--keep_ids",
    is_flag=True,
    default=False,
    help="Do not change the record IDs. Useful when importing an existing sample.",
)
@click.option(
    "--reset_records",
    default="NA",
    type=str,
    help="Reset record metadata to the imported version. "
    "Format: --reset_records ID1,ID2,ID3",
)
@click.option(
    "-rid",
    "--reset_ids",
    is_flag=True,
    default=False,
    help="Reset IDs that have been changed (to fix the sort order in records.bib)",
)
@click.option(
    "-d",
    "--debug",
    type=str,
    help="Debug the preparation step for a selected record (can be 'all').",
)
@click.option(
    "-scs",
    "--setup_custom_script",
    is_flag=True,
    default=False,
    help="Setup template for custom prep script.",
)
@click.option(
    "-df",
    "--debug_file",
    type=click.Path(exists=True),
    help="Debug the preparation step for a selected record (in a file).",
)
@click.option("-f", "--force", is_flag=True, default=False)
@click.pass_context
def prep(
    ctx,
    similarity,
    keep_ids,
    reset_records,
    reset_ids,
    debug,
    debug_file,
    setup_custom_script,
    force,
) -> None:
    """Prepare records"""

    import colrev.prep

    # pylint: disable=import-outside-toplevel
    # TODO : catch inside prep:
    from sqlite3 import OperationalError

    try:
        review_manager = colrev.review_manager.ReviewManager(
            force_mode=force, debug_mode=debug
        )
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    prep_operation = colrev.prep.Preparation(
        review_manager=review_manager, similarity=similarity
    )
    if reset_records != "NA":
        try:
            reset_records = str(reset_records)
        except ValueError:
            pass
        reset_records = reset_records.split(",")
        prep_operation.reset_records(reset_ids=reset_records)
    elif reset_ids:
        prep_operation.reset_ids()
    elif debug or debug_file:
        prep_operation.main(keep_ids=keep_ids, debug_ids=debug, debug_file=debug_file)
    elif setup_custom_script:
        prep_operation.setup_custom_script()
        print("Activated custom_prep_script.py.")
        print("Please check and adapt its position in the settings.json and commit.")
    else:
        try:
            prep_operation.main(keep_ids=keep_ids)
            print()
            print("Please check the changes (especially those with low_confidence)")
            print("To reset record(s) based on their ID, run")
            print("   colrev prep --reset_records ID1,ID2,...")
            print()
        except colrev_exceptions.ServiceNotAvailableException as exc:
            print(exc)
            print("You can use the force mode to override")
            print("  colrev prep -f")
        except colrev_exceptions.MissingDependencyError as exc:
            print(exc)
        except OperationalError as exc:
            logging.error(
                f"SQLite Error: {exc}. "
                "Another colrev process is accessing a shared resource. "
                "Please try again later."
            )


def view_dedupe_details(review_manager) -> None:
    import colrev.dedupe

    dedupe_operation = colrev.dedupe.Dedupe(
        review_manager=review_manager, notify_state_transition_process=False
    )
    info = dedupe_operation.get_info()

    if len(info["same_source_merges"]) > 0:
        print(f"\n\n{colors.RED}Same source merges to check:{colors.END}")
        print("\n- " + "\n- ".join(info["same_source_merges"]))


@main.command(help_priority=6)
@click.option(
    "-f",
    "--fix_errors",
    is_flag=True,
    default=False,
    help="Fix errors marked in duplicates_to_validate.xlsx "
    "or non_duplicates_to_validate.xlsx or "
    "a dupes.txt file containing comma-separated ID tuples",
)
@click.option("-v", "--view", is_flag=True, default=False, help="View dedupe info")
@click.option(
    "-m",
    "--merge_threshold",
    type=float,
    help="Confidence threshold for automated merging (dedupe.io confidence)",
)
@click.option(
    "-p",
    "--partition_threshold",
    type=float,
    help="Partition threshold for duplicate clustering (dedupe.io partition)",
)
@click.option(
    "--source_comparison",
    is_flag=True,
    default=False,
    help="Export a spreadsheet for (non-matched) source comparison",
)
@click.option("--force", is_flag=True, default=False)
@click.pass_context
def dedupe(
    ctx,
    fix_errors,
    view,
    merge_threshold,
    partition_threshold,
    source_comparison,
    force,
) -> None:
    """Deduplicate records

    Duplicate identification and merging proceeds as follows:

        1. Training of an active learning (AL) deduplication model
          (based on dedupe.io and safeguards)

        2. Automated deduplication based on AL model

        3. Summaries (duplicates_to_validate.xlsx and non_duplicates_to_validate.xlsx)
          are exported for efficient validation and correction
          (colrev dedupe --fix_errors)

    When the sample size does not allow you to train an AL model (too small),
    deduplication will switch to a simple approach based on a fixed similarity measure

    When the sample size is too big, the blocking and indexing
    is stored in a PostgreSQL database (to avoid excessive RAM use)

    Duplicates can only occur within the set of new records
    (colrev status *md_prepared*) and between the set of new records and
    the set of records that have already been deduplicated
    (colrev_status *md_processed* or beyond).
    Records that are not prepared (colrev_status *md_imported*,
    *md_needs_manual_preparation*) are not considered for deduplication.
    The state model (colrev_status) ensures that users do not have to check
    potential duplicates within the deduplicated set repeatedly.

    Once records are marked as *processed* (or beyond),

    All steps rely on the LocalIndex to implement false positive safeguards against

        - Accidentally merging records that are non-duplicates

        - Accidentally merging records from the same source
    """
    import colrev.dedupe

    try:
        review_manager = colrev.review_manager.ReviewManager(force_mode=force)
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        if fix_errors:
            dedupe_operation = colrev.dedupe.Dedupe(review_manager=review_manager)
            dedupe_operation.fix_errors()
            print(
                "You can manually remove the duplicates_to_validate.xlsx, "
                "non_duplicates_to_validate.xlsx, and dupes.txt files."
            )

        elif view:
            view_dedupe_details(review_manager)

        elif source_comparison:
            dedupe_operation = colrev.dedupe.Dedupe(review_manager=review_manager)
            dedupe_operation.source_comparison()

        else:
            logging.basicConfig()
            logging.getLogger("dedupe.canopy_index").setLevel(logging.WARNING)
            saved_args = locals()
            if "fix_errors" in saved_args:
                del saved_args["fix_errors"]

            dedupe_operation = colrev.dedupe.Dedupe(review_manager=review_manager)
            dedupe_operation.main()

    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")

    except colrev_exceptions.DedupeError as exc:
        logging.error(f"DedupeError: {exc}")


@main.command(help_priority=7)
@click.option(
    "--stats",
    is_flag=True,
    default=False,
    help="Print statistics of records with colrev_status md_needs_manual_preparation",
)
@click.pass_context
def prep_man(ctx, stats) -> None:
    """Manual preparation of records (not yet fully implemented)"""
    import colrev.prep_man

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    prep_man_operation = colrev.prep_man.PrepMan(review_manager=review_manager)

    if stats:
        prep_man_operation.prep_man_stats()
    else:
        prep_man_operation.main()


@main.command(help_priority=9)
@click.option(
    "--include_all",
    is_flag=True,
    default=False,
    help="Include all records in prescreen",
)
@click.option(
    "--export_format",
    type=click.Choice(["CSV", "XLSX"], case_sensitive=False),
    help="Export table with the screening decisions",
)
@click.option(
    "--import_table",
    type=click.Path(exists=True),
    help="Import file with the screening decisions (csv supported)",
)
@click.option(
    "--create_split",
    type=int,
    help="Split the prescreen between n researchers "
    + "(same size, non-overlapping samples)",
)
@click.option(
    "--split",
    type=str,
    default="",
    help="Prescreen a split sample",
)
@click.option(
    "-scs",
    "--setup_custom_script",
    is_flag=True,
    default=False,
    help="Setup template for custom search script.",
)
@click.pass_context
def prescreen(
    ctx,
    include_all,
    export_format,
    import_table,
    create_split,
    split,
    setup_custom_script,
) -> None:
    """Pre-screen based on titles and abstracts"""
    import colrev.prescreen

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        prescreen_operation = colrev.prescreen.Prescreen(review_manager=review_manager)

        if export_format:
            prescreen_operation.export_table(export_table_format=export_format)
        elif import_table:
            prescreen_operation.import_table(import_table_path=import_table)
        elif include_all:
            prescreen_operation.include_all_in_prescreen()
        elif create_split:
            splits = prescreen_operation.create_prescreen_split(
                create_split=create_split
            )
            for created_split in splits:
                print(created_split + "\n")
        elif setup_custom_script:
            prescreen_operation.setup_custom_script()
            print("Activated custom_prescreen_script.py.")
        else:
            prescreen_operation.main(split_str=split)

    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")
    except colrev_exceptions.CleanRepoRequiredError as exc:
        logging.error(f"CleanRepoRequiredError: {exc}")


@main.command(help_priority=10)
@click.option(
    "--include_all",
    is_flag=True,
    default=False,
    help="Include all records in the screen",
)
@click.option(
    "-ac",
    "--add_criterion",
    type=str,
    help="Add a screening criterion. "
    "Format: -ac 'criterion_name,criterion explanation'",
)
@click.option(
    "-dc",
    "--delete_criterion",
    type=str,
    help="Delete a screening criterion. Format: -dc 'criterion_name'",
)
@click.option(
    "--create_split",
    type=int,
    help="Split the prescreen between n researchers "
    + "(same size, non-overlapping samples)",
)
@click.option(
    "--split",
    type=str,
    default="",
    help="Prescreen a split sample",
)
@click.option(
    "-scs",
    "--setup_custom_script",
    is_flag=True,
    default=False,
    help="Setup template for custom search script.",
)
@click.pass_context
def screen(
    ctx,
    include_all,
    add_criterion,
    delete_criterion,
    create_split,
    split,
    setup_custom_script,
) -> None:
    """Screen based on exclusion criteria and fulltext documents"""
    import colrev.screen

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        screen_operation = colrev.screen.Screen(review_manager=review_manager)
        if include_all:
            screen_operation.include_all_in_screen()
        elif add_criterion:
            screen_operation.add_criterion(criterion_to_add=add_criterion)
        elif delete_criterion:
            screen_operation.delete_criterion(criterion_to_delete=delete_criterion)
        elif create_split:
            splits = screen_operation.create_screen_split(create_split=create_split)
            for created_split in splits:
                print(created_split + "\n")
        elif setup_custom_script:
            screen_operation.setup_custom_script()
            print("Activated custom_screen_script.py.")
        else:
            screen_operation.main(split_str=split)
    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")


@main.command(help_priority=11)
@click.option(
    "-c",
    "--copy-to-repo",
    is_flag=True,
    default=False,
    help="Copy PDF files to the repository (the /pdfs directory)",
)
@click.option(
    "-r",
    "--rename",
    is_flag=True,
    default=False,
    help="Rename the PDF files according to record IDs",
)
@click.option(
    "--relink_files",
    is_flag=True,
    default=False,
    help="Recreate links to PDFs based on colrev pdf-IDs (when PDFs were renamed)",
)
@click.option(
    "-scs",
    "--setup_custom_script",
    is_flag=True,
    default=False,
    help="Setup template for custom search script.",
)
@click.pass_context
def pdf_get(ctx, copy_to_repo, rename, relink_files, setup_custom_script) -> None:
    """Retrieve PDFs to the default pdf directory (/pdfs)"""
    import colrev.pdf_get

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        if relink_files:
            pdf_get_operation = colrev.pdf_get.PDFRetrieval(
                review_manager=review_manager, notify_state_transition_process=False
            )
            pdf_get_operation.relink_files()
        elif copy_to_repo:
            pdf_get_operation = colrev.pdf_get.PDFRetrieval(
                review_manager=review_manager
            )
            pdf_get_operation.copy_pdfs_to_repo()
        elif rename:
            pdf_get_operation = colrev.pdf_get.PDFRetrieval(
                review_manager=review_manager
            )
            pdf_get_operation.rename_pdfs()
        elif setup_custom_script:
            pdf_get_operation = colrev.pdf_get.PDFRetrieval(
                review_manager=review_manager, notify_state_transition_process=False
            )
            pdf_get_operation.setup_custom_script()
            print("Activated custom_pdf_get_script.py.")
        else:
            pdf_get_operation = colrev.pdf_get.PDFRetrieval(
                review_manager=review_manager
            )
            pdf_get_operation.main()

    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")


@main.command(help_priority=12)
@click.option(
    "--update_colrev_pdf_ids", is_flag=True, default=False, help="Update colrev_pdf_ids"
)
@click.option(
    "--reprocess",
    is_flag=True,
    default=False,
    help="Prepare all PDFs again (pdf_needs_manual_preparation).",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    default=False,
    help="Debug",
)
@click.option(
    "-scs",
    "--setup_custom_script",
    is_flag=True,
    default=False,
    help="Setup template for custom search script.",
)
@click.pass_context
def pdf_prep(ctx, update_colrev_pdf_ids, reprocess, debug, setup_custom_script) -> None:
    """Prepare PDFs

    This involves:

        - Checking for machine readability and applying OCR if necessary

        - Removing coverpages and appended pages

        - Validating the PDF against the record metadata

        - Checking for completeness (number of pages according to record metadata)
    """
    import colrev.pdf_prep

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        pdf_prep_operation = colrev.pdf_prep.PDFPreparation(
            review_manager=review_manager, reprocess=reprocess, debug=debug
        )

        if update_colrev_pdf_ids:
            pdf_prep_operation.update_colrev_pdf_ids()
        elif setup_custom_script:
            pdf_prep_operation.setup_custom_script()
            print("Activated custom_pdf_prep_script.py.")
        else:
            pdf_prep_operation.main()

    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")


@main.command(help_priority=13)
@click.pass_context
@click.option(
    "-e",
    "--export",
    is_flag=True,
    default=False,
    help="Export spreadsheet.",
)
def pdf_get_man(ctx, export) -> None:
    """Get PDFs manually"""
    import colrev.pdf_get_man

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        pdf_get_man_operation = colrev.pdf_get_man.PDFRetrievalMan(
            review_manager=review_manager
        )
        if export:

            records = pdf_get_man_operation.review_manager.dataset.load_records_dict()
            pdf_get_man_records = [
                r
                for r in records.values()
                if r["colrev_status"]
                in [
                    colrev.record.RecordState.pdf_needs_manual_retrieval,
                    colrev.record.RecordState.rev_prescreen_included,
                ]
            ]
            pdf_get_man_records_df = pd.DataFrame.from_records(pdf_get_man_records)
            pdf_get_man_records_df = pdf_get_man_records_df[
                pdf_get_man_records_df.columns.intersection(
                    {
                        "ID",
                        "author",
                        "year",
                        "title",
                        "journal",
                        "booktitle",
                        "volume",
                        "number",
                        "url",
                        "doi",
                    }
                )
            ]
            pdf_get_man_records_df.to_csv("pdf_get_man_records.csv", index=False)
            pdf_get_man_operation.review_manager.logger.info(
                "Created pdf_get_man_records.csv"
            )

        else:
            pdf_get_man_operation.main()
    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")


def delete_first_pages_cli(pdf_get_man_operation, record_id) -> None:

    records = pdf_get_man_operation.review_manager.dataset.load_records_dict()
    while True:
        if record_id in records:
            record = records[record_id]
            if "file" in record:
                print(record["file"])
                pdf_path = pdf_get_man_operation.review_manager.path / Path(
                    record["file"]
                )
                pdf_get_man_operation.extract_coverpage(pdf_path)
            else:
                print("no file in record")
        if "n" == input("Extract coverpage from another PDF? (y/n)"):
            break
        record_id = input("ID of next PDF for coverpage extraction:")


@main.command(help_priority=14)
@click.option(
    "-dfp",
    "--delete_first_page",
    type=str,
    help="Delete first page of PDF. Format: --delete_first_page ID",
)
@click.option(
    "--stats",
    is_flag=True,
    default=False,
    help="Print statistics of records with colrev_status pdf_needs_manual_preparation",
)
@click.option(
    "--extract",
    is_flag=True,
    default=False,
    help="Extract records for manual_preparation (to csv and bib)",
)
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply manual preparation (from csv or bib)",
)
@click.pass_context
def pdf_prep_man(ctx, delete_first_page, stats, extract, apply) -> None:
    """Prepare PDFs manually"""
    import colrev.pdf_prep_man

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        if delete_first_page:
            pdf_prep_man_operation = colrev.pdf_prep_man.PDFPrepMan(
                review_manager=review_manager
            )
            delete_first_pages_cli(pdf_prep_man_operation, delete_first_page)
            return

        pdf_prep_man_operation = colrev.pdf_prep_man.PDFPrepMan(
            review_manager=review_manager
        )
        if stats:
            pdf_prep_man_operation.pdf_prep_man_stats()
        elif extract:
            pdf_prep_man_operation.extract_needs_pdf_prep_man()
        elif apply:
            pdf_prep_man_operation.apply_pdf_prep_man()
        else:
            pdf_prep_man_operation.main()
    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")


@main.command(help_priority=15)
@click.option(
    "--profile",
    is_flag=True,
    default=False,
    help="Create a sample profile (papers per journal and year)",
)
@click.option(
    "--reading_heuristics",
    is_flag=True,
    default=False,
    help="Heuristics to prioritize reading efforts",
)
@click.option(
    "-a",
    "--add_endpoint",
    type=str,
    help="Add a data_format endpoint (e.g., MANUSCRIPT,STRUCTURED)",
)
@click.option(
    "-scs",
    "--setup_custom_script",
    is_flag=True,
    default=False,
    help="Setup template for custom search script.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Option to override process preconditions",
)
@click.pass_context
def data(
    ctx, profile, reading_heuristics, add_endpoint, setup_custom_script, force
) -> None:
    """Extract data"""
    import colrev.data

    try:
        review_manager = colrev.review_manager.ReviewManager(force_mode=force)
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:
        data_operation = colrev.data.Data(review_manager=review_manager)
        if profile:
            data_operation.profile()
        elif reading_heuristics:
            heuristic_results = data_operation.reading_heuristics()
            review_manager.p_printer.pprint(heuristic_results)
            return
        elif setup_custom_script:
            data_operation.setup_custom_script()
            print("Activated custom_data_script.py.")
            print("Please update the data_format in settings.json and commit.")
        elif add_endpoint:

            if add_endpoint in data_operation.built_in_scripts:
                endpoint_class = data_operation.built_in_scripts[add_endpoint][
                    "endpoint"
                ]
                endpoint = endpoint_class(
                    DATA=data_operation, SETTINGS={"name": add_endpoint}
                )

                default_endpoint_conf = endpoint.get_default_setup()

                if "MANUSCRIPT" == add_endpoint:
                    if "y" == input("Select a custom word template (y/n)?"):

                        template_name = input(
                            'Please copy the word template to " \
                        "the project directory and enter the filename.'
                        )
                        default_endpoint_conf["word_template"] = template_name
                    else:
                        print("Adding APA as a default")

                    if "y" == input("Select a custom citation stlye (y/n)?"):
                        print(
                            "Citation stlyes are available at: \n"
                            "https://github.com/citation-style-language/styles"
                        )
                        csl_link = input(
                            "Please select a citation style and provide the link."
                        )
                        ret = requests.get(csl_link, allow_redirects=True)
                        with open(Path(csl_link).name, "wb") as file:
                            file.write(ret.content)
                        default_endpoint_conf["csl_style"] = Path(csl_link).name
                    else:
                        print("Adding APA as a default")

                    data_operation.review_manager.dataset.add_changes(
                        path=default_endpoint_conf["csl_style"]
                    )
                    data_operation.review_manager.dataset.add_changes(
                        path=default_endpoint_conf["word_template"]
                    )
                    # TODO : check whether template_name is_file
                    # and csl_link.name is_file()

                data_operation.add_data_endpoint(default_endpoint_conf)
                data_operation.review_manager.create_commit(
                    msg="Add data endpoint",
                    script_call="colrev data",
                )

                # Note : reload updated settings
                review_manager = colrev.review_manager.ReviewManager(force_mode=force)
                data_operation = colrev.data.Data(review_manager=review_manager)

            else:
                print("Data format not available")

            ret = data_operation.main()
            if ret["ask_to_commit"]:
                if "y" == input("Create commit (y/n)?"):
                    review_manager.create_commit(
                        msg="Data and synthesis", manual_author=True
                    )
        else:
            ret = data_operation.main()
            if ret["ask_to_commit"]:
                if "y" == input("Create commit (y/n)?"):
                    review_manager.create_commit(
                        msg="Data and synthesis", manual_author=True
                    )
            if ret["no_endpoints_registered"]:
                print(
                    "No data format not specified. "
                    "To register a data endpoint, "
                    "use one (or several) of the following \n"
                    "    colrev data --add_endpoint MANUSCRIPT\n"
                    "    colrev data --add_endpoint STRUCTURED\n"
                    "    colrev data --add_endpoint PRISMA\n"
                    "    colrev data --add_endpoint ZETTLR\n"
                    "    colrev data --add_endpoint ENDNOTE"
                )

    except colrev_exceptions.ProcessOrderViolation as exc:
        logging.error(f"ProcessOrderViolation: {exc}")


def validate_commit(ctx, param, value):
    if value is None:
        return value

    # pylint: disable=import-outside-toplevel
    import git

    repo = git.Repo()
    rev_list = list(repo.iter_commits())

    if value in [x.hexsha for x in rev_list]:
        return value

    print("Error: Invalid value for '--commit': not a git commit id\n")
    print("Select any of the following commit ids:\n")
    print("commit-id".ljust(41, " ") + "date".ljust(24, " ") + "commit message")
    commits_for_checking = []
    for commit in reversed(list(rev_list)):
        commits_for_checking.append(commit)
    for commit in rev_list:
        print(
            commit.hexsha,
            datetime.datetime.fromtimestamp(commit.committed_date),
            " - ",
            commit.message.split("\n")[0],
        )
    print("\n")
    raise click.BadParameter("not a git commit id")


@main.command(help_priority=16)
@click.option(
    "--scope",
    type=click.Choice(["prepare", "merge", "all", "unspecified"], case_sensitive=False),
    default="unspecified",
    help="prepare, merge, or all.",
)
@click.option(
    "--properties", is_flag=True, default=False, help="Git commit id to validate."
)
@click.option(
    "--commit",
    help="Git commit id to validate.",
    default=None,
    callback=validate_commit,
)
@click.pass_context
def validate(ctx, scope, properties, commit) -> None:
    """Validate changes"""
    import colrev.validate

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    validate_operation = colrev.validate.Validate(review_manager=review_manager)
    validation_details = validate_operation.main(
        scope=scope, properties=properties, target_commit=commit
    )

    if 0 == len(validation_details):
        print("No substantial changes.")
        return

    # pylint: disable=duplicate-code
    keys = [
        "author",
        "title",
        "journal",
        "booktitle",
        "year",
        "volume",
        "number",
        "pages",
    ]

    for record_a, record_b, difference in validation_details:
        # Escape sequence to clear terminal output for each new comparison
        os.system("cls" if os.name == "nt" else "clear")
        if record_a["ID"] == record_b["ID"]:
            print(f"similarity: {str(round(difference, 4))} record {record_a['ID']}")
        else:
            print(
                f"similarity: {str(round(difference, 4))} "
                f"record {record_a['ID']} - {record_b['ID']}"
            )

        colrev.record.Record.print_diff_pair(
            record_pair=[record_a, record_b], keys=keys
        )

        user_selection = input("Validate [y,n,d,q]?")

        if "q" == user_selection:
            break
        if "y" == user_selection:
            continue

        # TODO: correct? if not, replace current record with old one


@main.command(help_priority=17)
@click.pass_context
@click.option("--id", help="Record ID to trace (citation_key).", required=True)
def trace(ctx, id) -> None:
    """Trace a record"""
    import colrev.trace

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    trace_operation = colrev.trace.Trace(review_manager=review_manager)
    trace_operation.main(ID=id)


@main.command(help_priority=18)
@click.pass_context
def paper(ctx) -> None:
    """Build the paper"""
    import colrev.paper

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    try:

        paper_operation = colrev.paper.Paper(review_manager=review_manager)
        paper_operation.main()
    except colrev_exceptions.NoPaperEndpointRegistered as exc:
        print(f"NoPaperEndpointRegistered: {exc}")
        print(
            "To register a paper endpoint, use \n"
            "    colrev data --add_endpoint MANUSCRIPT"
        )


@main.command(help_priority=19)
@click.option(
    "-p",
    "--path",
    type=click.Path(exists=True),
    help="Path to file(s)",
)
@click.pass_context
def distribute(ctx, path) -> None:
    """Distribute records to other local CoLRev repositories"""

    import colrev.distribute

    # pylint: disable=import-outside-toplevel
    from yaml import safe_load

    # Note : distribute is designed with the assumption that it is called from
    # within a colrev project.
    # In other cases, colrev.review_manager.ReviewManager() will fail.
    # Other use cases may be related to sync/export (from LocalIndex)

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    distribute_operation = colrev.distribute.Distribute(review_manager=review_manager)

    local_registry_path = Path.home().joinpath(".colrev/registry.yaml")
    if not os.path.exists(local_registry_path):
        print("no local repositories registered")
        return

    with open(local_registry_path, encoding="utf-8") as file:
        local_registry_df = pd.json_normalize(safe_load(file))
        local_registry = local_registry_df.to_dict("records")
        local_registry = [
            x for x in local_registry if "curated_metadata/" not in x["source_url"]
        ]

    valid_selection = False
    while not valid_selection:
        for i, local_source in enumerate(local_registry):
            print(
                f"{i+1} - {local_source['source_name']} ({local_source['source_url']})"
            )
        sel_str = input("Select target repository: ")
        sel = int(sel_str) - 1
        if sel in range(0, len(local_registry)):
            target = Path(local_registry[sel]["source_url"])
            valid_selection = True

    distribute_operation.main(path_str=path, target=target)


def print_environment_status() -> None:
    import colrev.environment

    environment_manager = colrev.environment.EnvironmentManager()

    environment_details = environment_manager.get_environment_details()

    print("\nCoLRev environment status\n")
    print("Index\n")
    if "up" == environment_details["index"]["status"]:
        print(f" - Status: {colors.GREEN}up{colors.END}")
        print(f' - Path          : {environment_details["index"]["path"]}')
        print(f' - Size          : {environment_details["index"]["size"]} records')
        print(f' - Last modified : {environment_details["index"]["last_modified"]}')
    else:
        print(f" - Status: {colors.RED}down{colors.END}")

    print("\nCoLRev projects\n")
    project_repos = [
        x
        for x in environment_details["local_repos"]["repos"]
        if "curated_metadata" not in x["source_url"]
    ]
    for colrev_repo in sorted(project_repos, key=lambda d: d["source_name"]):

        repo_stats = f' {colrev_repo["source_name"]}'
        if colrev_repo["remote"]:
            if colrev_repo["behind_remote"]:
                repo_stats += " (shared, behind remote)"
            else:
                repo_stats += " (shared)"
        print(repo_stats)

        if -1 != colrev_repo["progress"]:
            print(f'    - Progress : {colrev_repo["progress"]*100} %')
        else:
            print("    - Progress : ??")
        print(f'    - Size     : {colrev_repo["size"]} records')
        print(f'    - Path     : {colrev_repo["source_url"]}')

    print("\nCurated CoLRev resources\n")
    curated_repos = [
        x
        for x in environment_details["local_repos"]["repos"]
        if "curated_metadata" in x["source_url"]
    ]
    for colrev_repo in sorted(curated_repos, key=lambda d: d["source_name"]):
        repo_stats = (
            f' - {colrev_repo["source_name"].ljust(60, " ")}: '
            f'{str(colrev_repo["size"]).rjust(10, " ")} records'
        )
        if colrev_repo["behind_remote"]:
            repo_stats += " (behind remote)"
        print(repo_stats)

    print("\n")
    if len(environment_details["local_repos"]["broken_links"]) > 0:
        print("Broken links: \n")
        for broken_link in environment_details["local_repos"]["broken_links"]:
            print(f'- {broken_link["source_url"]}')


@main.command(help_priority=20)
@click.option(
    "-i", "--index", is_flag=True, default=False, help="Create the LocalIndex"
)
@click.option(
    "--install",
    help="Install a new resource providing its url "
    + "(e.g., a curated metadata repository)",
)
@click.option(
    "-a",
    "--analyze",
    is_flag=True,
    default=False,
    help="Analyze the LocalIndex for potential problems",
)
@click.option("--pull", is_flag=True, default=False, help="Pull curated metadata")
@click.option(
    "-s", "--status", is_flag=True, default=False, help="Print environment status"
)
@click.option("--start", is_flag=True, default=False, help="Start environment services")
@click.option("--stop", is_flag=True, default=False, help="Stop environment services")
@click.option(
    "--search",
    is_flag=True,
    default=False,
    help="Start opensearch dashboard service to search the LocalIndex",
)
@click.option(
    "-r",
    "--register",
    is_flag=True,
    default=False,
    help="Register a repository in the CoLRev environment",
)
@click.option(
    "-ur",
    "--unregister",
    type=click.Path(exists=True),
    help="Path of repository to remove from local registry.",
)
@click.pass_context
def env(
    ctx,
    index,
    install,
    analyze,
    pull,
    status,
    start,
    stop,
    search,
    register,
    unregister,
):
    """CoLRev environment commands"""
    import colrev.environment

    # pylint: disable=import-outside-toplevel
    import webbrowser
    import docker

    if install:
        env_resources = colrev.environment.Resources()
        if env_resources.install_curated_resource(curated_resource=install):
            print("Successfully installed curated resource.")
            print("To make it available to other projects, run")
            print("colrev env --index")

    elif pull:
        for (
            curated_resource
        ) in colrev.environment.EnvironmentManager.load_local_registry():
            curated_resource_path = curated_resource["source_url"]
            if "/curated_metadata/" not in curated_resource_path:
                continue
            review_manager = colrev.review_manager.ReviewManager(
                path_str=curated_resource_path
            )
            review_manager.dataset.pull_if_repo_clean()
            print(f"Pulled {curated_resource_path}")

    elif status:
        print_environment_status()

    elif start:
        _ = colrev.environment.LocalIndex()
        print("Started.")

    elif stop:
        client = docker.from_env()
        images_to_stop = [
            k for k, v in colrev.environment.EnvironmentManager.docker_images.items()
        ]
        for container in client.containers.list():
            if any(x in str(container.image) for x in images_to_stop):
                container.stop()
                print(f"Stopped container {container.name} ({container.image})")

    elif search:
        local_index = colrev.environment.LocalIndex()
        local_index.start_opensearch_docker_dashboards()
        print("Started.")
        webbrowser.open("http://localhost:5601/app/home#/", new=2)

    elif index:
        local_index = colrev.environment.LocalIndex()
        local_index.index()

    elif analyze:
        local_index = colrev.environment.LocalIndex()
        local_index.analyze()

    elif register:
        colrev.environment.EnvironmentManager.register_repo(path_to_register=Path.cwd())

    elif unregister is not None:
        local_registry = colrev.environment.EnvironmentManager.load_local_registry()
        if str(unregister) not in [x["source_url"] for x in local_registry]:
            logging.error(f"Not in local registry (cannot remove): {unregister}")
        else:
            local_registry = [
                x for x in local_registry if x["source_url"] != str(unregister)
            ]
            colrev.environment.EnvironmentManager.save_local_registry(
                updated_registry=local_registry
            )
            logging.info(f"Removed from local registry: {unregister}")


@main.command(help_priority=21)
# @click.option("-v", "--view", is_flag=True, default=False)
@click.option(
    "-u",
    "--upgrade",
    is_flag=True,
    default=False,
    help="Update to the latest CoLRev project version",
)
@click.option(
    "-uh",
    "--update_hooks",
    is_flag=True,
    default=False,
    help="Update the pre-commit hooks",
)
@click.option(
    "-m",
    "--modify",
    type=str,
    default="",
    help="Modify the settings through the command line",
)
@click.pass_context
def settings(ctx, upgrade, update_hooks, modify):
    """Settings of the CoLRev project"""

    # pylint: disable=import-outside-toplevel
    from subprocess import check_call
    from subprocess import DEVNULL
    from subprocess import STDOUT
    import json
    import ast
    import glom

    # from colrev.settings_editor import Settings

    # review_manager = colrev.review_manager.ReviewManager(force_mode=True)
    # SETTINGS = Settings(review_manager=review_manager)
    # SETTINGS.open_settings_editor()
    # input("stop")

    if upgrade:
        review_manager = colrev.review_manager.ReviewManager(force_mode=True)
        review_manager.upgrade_colrev()

    elif update_hooks:

        review_manager = colrev.review_manager.ReviewManager()
        print("Update pre-commit hooks")

        if review_manager.dataset.has_changes():
            print("Clean repo required. Commit or stash changes.")
            return

        scripts_to_call = [
            [
                "pre-commit",
                "autoupdate",
                "--repo",
                "https://github.com/geritwagner/colrev-hooks",
            ],
        ]
        for script_to_call in scripts_to_call:
            check_call(script_to_call, stdout=DEVNULL, stderr=STDOUT)

        review_manager.dataset.add_changes(path=".pre-commit-config.yaml")
        review_manager.create_commit(
            msg="Update pre-commit hooks", script_call="colrev settings --update"
        )
        print("Successfully updated pre-commit hooks")

    elif modify:

        review_manager = colrev.review_manager.ReviewManager()
        # TBD: maybe use glom.delete?
        # There is no simply append...
        # (we could replace the (last) position element with
        # keywords like prescreen.sripts.LAST_POSITION)
        # maybe prescreen.scripts.1.REPLACE/ADD/DELETE = ....
        # modify = 'dedupe.scripts=[{"endpoint":"simple_dedupe"}]'

        path, value_string = modify.split("=")
        value = ast.literal_eval(value_string)
        review_manager.logger.info(f"Change settings.{path} to {value}")

        with open("settings.json", encoding="utf-8") as file:
            project_settings = json.load(file)

        glom.assign(project_settings, path, value)

        with open("settings.json", "w", encoding="utf-8") as outfile:
            json.dump(project_settings, outfile, indent=4)

        review_manager.dataset.add_changes(path="settings.json")
        review_manager.create_commit(
            msg="Change settings", manual_author=True, saved_args=None
        )

    else:
        review_manager = colrev.review_manager.ReviewManager()
        print(f"Settings:\n{review_manager.settings}")
        print("\n")


@main.command(help_priority=22)
@click.pass_context
def sync(ctx):
    """Sync records from CoLRev environment to non-CoLRev repo"""
    import colrev.sync

    sync_operation = colrev.sync.Sync()
    sync_operation.get_cited_papers()

    if len(sync_operation.non_unique_for_import) > 0:
        print("Non-unique keys to resolve:")
        # Resolve non-unique cases
        for case in sync_operation.non_unique_for_import:
            for val in case.values():
                # TODO: there may be more collisions (v3, v4)
                v_1 = sync_operation.format_ref(reference=val[0])
                v_2 = sync_operation.format_ref(reference=val[1])
                if v_1.lower() == v_2.lower():
                    sync_operation.add_to_records_to_import(record=val[0])
                    continue
                print("\n")
                print(f"1: {v_1}")
                print("      " + val[0].get("source_url", ""))
                print("")
                print(f"2: {v_2}")
                print("      " + val[1].get("source_url", ""))
                user_selection = input("Import version 1 or 2 (or skip)?")
                if "1" == user_selection:
                    sync_operation.add_to_records_to_import(record=val[0])
                    continue
                if "2" == user_selection:
                    sync_operation.add_to_records_to_import(record=val[1])
                    continue

    sync_operation.add_to_bib()


@main.command(help_priority=23)
@click.option(
    "-r",
    "--records_only",
    is_flag=True,
    default=False,
    help="Update records only",
)
@click.option(
    "-p",
    "--project_only",
    is_flag=True,
    default=False,
    help="Push project only",
)
@click.pass_context
def pull(ctx, records_only, project_only):
    """Pull CoLRev project remote and record updates"""
    import colrev.pull

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    pull_operation = colrev.pull.Pull(review_manager=review_manager)
    pull_operation.main(records_only=records_only, project_only=project_only)


@main.command(help_priority=24)
@click.argument("git_url")
@click.pass_context
def clone(ctx, git_url):
    """Create local clone from shared CoLRev repository with git_url"""
    import colrev.clone

    clone_operation = colrev.clone.Clone(git_url=git_url)
    clone_operation.clone_git_repo()


@main.command(help_priority=26)
@click.option(
    "-r",
    "--records_only",
    is_flag=True,
    default=False,
    help="Update records only",
)
@click.option(
    "-p",
    "--project_only",
    is_flag=True,
    default=False,
    help="Push project only",
)
@click.pass_context
def push(ctx, records_only, project_only):
    """Push CoLRev project remote and record updates"""

    import colrev.push

    try:
        review_manager = colrev.review_manager.ReviewManager()
    except MissingValueError as exc:
        print(f"Error in settings.json: {exc}")
        print("To solve this, use\n  colrev settings --upgrade")
        return

    push_operation = colrev.push.Push(review_manager=review_manager)
    push_operation.main(records_only=records_only, project_only=project_only)


@main.command(help_priority=25)
@click.pass_context
def service(ctx):
    """Service for real-time reviews"""

    import colrev.service

    review_manager = colrev.review_manager.ReviewManager()
    try:

        colrev.service.Service(review_manager=review_manager)

    except KeyboardInterrupt:
        print("\nPressed ctrl-c. Shutting down service")

    if review_manager.dataset.has_changes():
        if "y" == input("Commit current changes (y/n)?"):
            review_manager.create_commit(
                msg="Update (work on realtime review)", realtime_override=True
            )
    else:
        print("No changes to commit")


def validate_show(ctx, param, value):
    if value not in ["sample", "settings", "prisma", "venv"]:
        raise click.BadParameter("Invalid argument")


@main.command(help_priority=26)
@click.argument("keyword")
@click.pass_context
def show(ctx, keyword, callback=validate_show, required=True):
    """Show aspects (sample, ...)"""

    import colrev.process

    review_manager = colrev.review_manager.ReviewManager()
    if "sample" == keyword:

        colrev.process.CheckProcess(review_manager=review_manager)
        records = review_manager.dataset.load_records_dict()
        sample = [
            r
            for r in records.values()
            if r["colrev_status"]
            in [
                colrev.record.RecordState.rev_synthesized,
                colrev.record.RecordState.rev_included,
            ]
        ]
        if 0 == len(sample):
            print("No records included in sample (yet)")

        for sample_r in sample:
            colrev.record.Record(data=sample_r).print_citation_format()
        # TODO : print sample size, distributions over years/journals

    elif "settings" == keyword:
        print(f"Settings:\n{review_manager.settings}")

    elif "prisma" == keyword:

        stat = review_manager.get_status_freq()
        print(stat)

        print(
            "Records identified through database searching: "
            f"{stat['colrev_status']['overall']['md_retrieved']}"
        )

    elif "venv" == keyword:
        # pylint: disable=import-outside-toplevel
        import platform

        # TODO : test installation of colrev in venv

        current_platform = platform.system()
        if "Linux" == current_platform:
            print("Detected platform: Linux")
            if not Path("venv").is_dir():
                print("To create virtualenv, run")
                print(f"  {colors.ORANGE}python3 -m venv venv{colors.END}")
            print("To activate virtualenv, run")
            print(f"  {colors.ORANGE}source venv/bin/activate{colors.END}")
            print("To install colrev/colrev, run")
            print(f"  {colors.ORANGE}python -m pip install colrev colrev{colors.END}")
            print("To deactivate virtualenv, run")
            print(f"  {colors.ORANGE}deactivate{colors.END}")
        elif "Darwin" == current_platform:
            print("Detected platform: MacOS")
            if not Path("venv").is_dir():
                print("To create virtualenv, run")
                print(f"  {colors.ORANGE}python3 -m venv venv{colors.END}")
            print("To activate virtualenv, run")
            print(f"  {colors.ORANGE}source venv/bin/activate{colors.END}")
            print("To install colrev/colrev, run")
            print(f"  {colors.ORANGE}python -m pip install colrev colrev{colors.END}")
            print("To deactivate virtualenv, run")
            print(f"  {colors.ORANGE}deactivate{colors.END}")
        elif "Windows" == current_platform:
            print("Detected platform: Windows")
            if not Path("venv").is_dir():
                print("To create virtualenv, run")
                print(f"  {colors.ORANGE}python -m venv venv{colors.END}")
            print("To activate virtualenv, run")
            print(f"  {colors.ORANGE}venv\\Scripts\\Activate.ps1{colors.END}")
            print("To install colrev/colrev, run")
            print(f"  {colors.ORANGE}python -m pip install colrev colrev{colors.END}")
            print("To deactivate virtualenv, run")
            print(f"  {colors.ORANGE}deactivate{colors.END}")
        else:
            print(
                "Platform not detected... "
                "cannot provide infos in how to activate virtualenv"
            )
    else:
        print("Keyword unknown")


@main.command(hidden=True)
@click.option(
    "-i", "--case-insensitive/--no-case-insensitive", help="Case insensitive completion"
)
@click.argument(
    "shell",
    required=False,
    type=click_completion.DocumentedChoice(click_completion.core.shells),
)
def show_click(shell, case_insensitive):
    """Show the click-completion-command completion code"""
    extra_env = (
        {"_CLICK_COMPLETION_COMMAND_CASE_INSENSITIVE_COMPLETE": "ON"}
        if case_insensitive
        else {}
    )
    click.echo(click_completion.core.get_code(shell, extra_env=extra_env))


@main.command(hidden=True)
@click.option(
    "--append/--overwrite", help="Append the completion code to the file", default=None
)
@click.option(
    "-i", "--case-insensitive/--no-case-insensitive", help="Case insensitive completion"
)
@click.argument(
    "shell",
    required=False,
    type=click_completion.DocumentedChoice(click_completion.core.shells),
)
@click.argument("path", required=False)
def install_click(append, case_insensitive, shell, path):
    """Install the click-completion-command completion"""
    extra_env = (
        {"_CLICK_COMPLETION_COMMAND_CASE_INSENSITIVE_COMPLETE": "ON"}
        if case_insensitive
        else {}
    )
    shell, path = click_completion.core.install(
        shell=shell, path=path, append=append, extra_env=extra_env
    )
    click.echo(f"{shell} completion installed in {path}")
