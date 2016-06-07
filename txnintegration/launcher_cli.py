# Copyright 2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------------

import os
import sys
import argparse
import cmd
import pprint
import traceback
import tempfile
import time
import logging
import shutil
import tarfile

from txnintegration.exceptions import ExitError
from txnintegration.validator_network_manager import ValidatorNetworkManager
from txnintegration.utils import parse_configuration_file, \
    prompt_yes_no, find_txn_validator

logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)


def parse_args(args):
    parser = argparse.ArgumentParser()

    # use system or dev paths...
    parser.add_argument('--validator',
                        help='Fully qualified path to the txnvalidator to run',
                        default=None)
    parser.add_argument('--config',
                        help='Base validator config file',
                        default=None)
    parser.add_argument('--count',
                        help='Number of validators to launch',
                        default=1,
                        type=int)
    parser.add_argument('--save-blockchain',
                        help='Save the blockchain to a file when the '
                             'network is shutdown. This is the name of the '
                             'tar.gz file that the blockchain will be saved '
                             'in. ',
                        default=None)
    parser.add_argument('--load-blockchain',
                        help='load an existing blockchain from file. This '
                             'is a file name that points to a tar.gz that '
                             'was generated from a previous run using the '
                             '--save-blockchain option.',
                        default=None)
    parser.add_argument('--data-dir',
                        help='Where to store the logs, data, etc for the '
                             'network',
                        default=None)
    parser.add_argument('--log-level',
                        help='LogLevel to run the validators at.',
                        default="WARNING")

    return parser.parse_args(args)


def get_archive_config(data_dir, archive_name):
    tar = tarfile.open(archive_name, "r|gz")
    for f in tar:
        if os.path.basename(f.name) == 'validator-0.json':
            config = os.path.join(data_dir, "config.json")
            if os.path.exists(config):
                os.remove(config)
            tar.extract(f, data_dir)
            os.rename(os.path.join(data_dir, f.name), config)
            os.rmdir(os.path.join(data_dir, os.path.dirname(f.name)))
            break
    tar.close()
    return config


def configure(opts):
    scriptdir = os.path.dirname(os.path.realpath(__file__))

    # Find the validator to use
    if opts.validator is None:
        opts.validator = find_txn_validator()
        if not os.path.isfile(opts.validator):
            print "txnvalidator: {}".format(opts.validator)
            raise ExitError("Could not find txnvalidator.")
    else:
        if not os.path.isfile(opts.validator):
            print "txnvalidator: {}".format(opts.validator)
            raise ExitError("txnvalidator script does not exist.")

    # Create directory -- after the params have been validated
    if opts.data_dir is None:
        opts.data_dir_is_tmp = True  # did we make up a directory
        opts.data_dir = tempfile.mkdtemp()
    else:
        opts.data_dir = os.path.abspath(opts.data_dir)
        if not os.path.exists(opts.data_dir):
            os.makedirs(opts.data_dir)

    if opts.load_blockchain is not None:
        if not os.path.isfile(opts.load_blockchain):
            raise ExitError("Blockchain archive to load {} does not "
                            "exist.".format(opts.load_blockchain))
        else:
            opts.config = get_archive_config(opts.data_dir,
                                             opts.load_blockchain)
            if opts.config is None:
                raise ExitError("Could not read config from Blockchain "
                                "archive: {}".format(opts.load_blockchain))

    validator_config = {}

    if opts.config is not None:
        if os.path.exists(opts.config):
            validator_config = parse_configuration_file(opts.config)
        else:
            raise ExitError("Config file does not exist: {}".format(
                opts.config))
    else:
        opts.config = os.path.realpath(os.path.join(scriptdir, "..", "etc",
                                                    "txnvalidator.js"))
        print "No config file specified, loading  {}".format(opts.config)
        if os.path.exists(opts.config):
            validator_config = parse_configuration_file(opts.config)
        else:
            raise ExitError(
                "Default config file does not exist: {}".format(opts.config))

    keys = [
        'NodeName',
        'Host',
        'HttpPort',
        'Port',
        'LogFile',
        'LogLevel',
        'KeyFile',
        "AdministrationNode",
        "DataDirectory",
        "GenesisLedger",
    ]
    if any(k in validator_config for k in keys):
        print "Overriding the following keys from validator configuration " \
              "file: {}".format(opts.config)
        for k in keys:
            if k in validator_config:
                print "\t{}".format(k)
                del validator_config[k]

    opts.count = max(1, opts.count)
    opts.validator_config = validator_config
    opts.validator_config['LogLevel'] = opts.log_level

    print "Configuration:"
    pp.pprint(opts.__dict__)


class ValidatorNetworkConsole(cmd.Cmd):
    pformat = '> '

    def __init__(self, vnm):
        self.prompt = 'launcher_cli.py> '
        cmd.Cmd.__init__(self)
        self.networkManager = vnm

    def do_config(self, args):
        """
        config
        :param args: index of the validator
        :return: Print the  validator configuration file
        """
        try:
            args = args.split()
            parser = argparse.ArgumentParser()
            parser.add_argument("id",
                                help='Validator index or node name',
                                default='0')
            options = parser.parse_args(args)

            id = options.id
            v = self.networkManager.validator(id)
            if v:
                v.dump_config()
            else:
                print "Invalid validator id: {}".format(args[0])
        except:
            print sys.exc_info()[0]

        return False

    def do_log(self, args):
        try:
            id = args
            v = self.networkManager.validator(id)
            if v:
                v.dump_log()
            else:
                print "Invalid validator  id: {}".format(args[0])
        except:
            print sys.exc_info()[0]

        return False

    def do_out(self, args):
        try:
            id = args[0]
            v = self.networkManager.validator(id)
            if v:
                v.dump_stdout()
            else:
                print "Invalid validator id: {}".format(args[0])
        except:
            print sys.exc_info()[0]

        return False

    def do_err(self, args):
        try:
            id = args[0]
            v = self.networkManager.validator(id)
            if v:
                v.dump_stderr()
            else:
                print "Invalid validator id: {}".format(args[0])
        except:
            print sys.exc_info()[0]

        return False

    def do_launch(self, args):
        """launch
        Launch another validator on the network
        """
        v = self.networkManager.launch_node()
        print "Validator {} launched.".format(v.Name)
        return False

    def do_launch_cmd(self, args):
        """lcmd
        Give the command to launch another validator on the network. This can
        be used for creating a node to debug on  the validator network.
        """
        v = self.networkManager.launch_node(False)
        print v.command
        return False

    def do_expand(self, args):
        """expand
        Launch additional validators on the network
        New validators connect to most recent existing validators
        """
        count = int(args[0])
        v = self.networkManager.staged_expand_network(count)
        print "Network expanded with {0} additional validators launched"\
            .format(len(v))
        return False

    def do_kill(self, args):
        try:
            id = args[0]
            v = self.networkManager.validator(id)
            if v:
                while v.is_running():
                    v.shutdown(True)
                    if v.is_running():
                        time.sleep(1)
                print "Validator {} killed.".format(v.Name)
            else:
                print "Invalid validator id: {}".format(args[0])
        except:
            print sys.exc_info()[0]

    def do_status(self, args):
        """status
            Show the status of the running validators
        """
        for l in self.networkManager.status():
            print l
        return False

    def do_exit(self, args):
        """exit
        Shutdown the simulator and exit the command loop
        """
        return True

    def do_EOF(self, args):
        # pylint: disable=invalid-name
        print ""
        return self.do_exit(args)


def main():
    networkManager = None
    errorOccured = False
    try:
        opts = parse_args(sys.argv[1:])
    except:
        # argparse reports details on the parameter error.
        sys.exit(1)

    try:
        # Discover configuration
        configure(opts)

        networkManager = ValidatorNetworkManager(
            txnvalidator=opts.validator,
            cfg=opts.validator_config,
            dataDir=opts.data_dir,
            blockChainArchive=opts.load_blockchain)
        # networkManager.launch_network(opts.count)
        networkManager.staged_launch_network(opts.count)

        # wait ...
        ctrl = ValidatorNetworkConsole(networkManager)
        ctrl.cmdloop("\nWelcome to the sawtooth txnvalidator network "
                     "manager interactive console")
    except KeyboardInterrupt:
        print "\nExiting"
    except ExitError as e:
        # this is an expected error/exit, don't print stack trace -
        # the code raising this exception is expected to have printed the error
        # details
        errorOccured = True
        print "\nFailed!\nExiting: {}".format(e)
    except:
        errorOccured = True
        traceback.print_exc()
        print "\nFailed!\nExiting: {}".format(sys.exc_info()[0])

    if networkManager:
        networkManager.shutdown()

    if opts.save_blockchain:
        print "Saving blockchain to {}".format(opts.save_blockchain)
        networkManager.create_result_archive(opts.save_blockchain)

    # if dir was auto-generated
    if opts and "data_dir_is_tmp" in opts \
            and opts.data_dir_is_tmp \
            and os.path.exists(opts.data_dir):
        deleteTestDir = True
        if errorOccured:
            deleteTestDir = prompt_yes_no(
                "Do you want to delete the data dir(logs, configs, etc)")
        if deleteTestDir:
            print "Cleaning temp data store {}".format(opts.data_dir)
            if os.path.exists(opts.data_dir):
                shutil.rmtree(opts.data_dir)
        else:
            print "Data directory {}".format(opts.data_dir)
    else:
        print "Data directory {}".format(opts.data_dir)


if __name__ == "__main__":
    main()
