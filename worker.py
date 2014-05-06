#-=- encoding: utf-8 -=-
from rq import Queue, Worker, Connection
#from rq import get_current_job
from rq.decorators import job
from vagrant import Vagrant
import os
import logging
import sys
import sh
import re
import json
from redis import Redis
redis_conn = Redis()

basedir = os.path.abspath(os.path.dirname(__file__))
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('{}/vagrant-worker.log'.format(basedir))
#formatter = logging.Formatter('%(levelname) -10s %(asctime)s %(module)s:%(lineno)s %(funcName)s %(message)s')

#handler.setFormatter(formatter)
logger.addHandler(handler)


@job('low', connection=redis_conn, timeout=40)
def ip(path):
    os.putenv('HOME', '/root')
    logger.debug('Getting IP from vagrant machine')
    ip = ''
    old_path = os.getcwd()
    os.chdir(path)

    try:
        machineType = sh.vagrant('status')
        logger.debug(machineType)

        if 'stopped' not in machineType:
            if 'virtualbox' in machineType:
                ips = sh.vagrant('ssh', '-c', 'ip addr list eth1')
                ips = str(ips)
                search = re.match(r'.* inet (.*)/24 brd', ips.stdout.replace('\n', ''))

                if search:
                    ip = search.group(1)
            elif 'lxc' in machineType:
                ips = sh.vagrant('ssh-config')
                ips = str(ips)
                search = re.findall('HostName (.*)\n', ips, re.M)
                if search:
                    ip = search[0]
                logger.debug(ip)

    except:
        logger.error('Unable to connect to machine to it\'s IP :: {}'
                     .format(path))

    os.chdir(old_path)
    return ip


@job('high', connection=redis_conn, timeout=600)
def run(path, eth, environment, provider='lxc'):
    old_path = os.getcwd()
    os.putenv('HOME', '/root')

    logger.debug('Bring up {} with eth {} and environment set to {} with provider {}'
                 .format(path, eth, environment, provider))

    status = _get_status(path)
    if 'not created' not in status and provider not in status:
        logger.debug('Machine already created with another provider,\
destroying first')
        try:
            os.chdir(path)
            sh.vagrant('destroy')
            os.chdir(old_path)

        except:
            logger.error('Failed to destroy machine {}'.format(path))

        logger.debug('Done destroying')

    try:
        os.chdir(path)
        os.environ['ETH'] = eth
        os.environ['ENVIRONMENT'] = environment
        os.environ['VAGRANT_DEFAULT_PROVIDER'] = provider
        sh.vagrant('up')
        os.chdir(old_path)
    except:
        logger.error('Failed to bring up machine {}'.format(path),
                     exc_info=True)
    logger.debug('Done bring up {}'.format(path))

    return json.dumps(_get_status(path))


@job('high', connection=redis_conn, timeout=600)
def stop(path):
    os.putenv('HOME', '/root')
    logger.debug('Bring down {}'.format(path))

    vagrant = Vagrant(path)
    try:
        vagrant.halt()
    except:
        logger.error('Failed to shut down machine {}'.format(path),
                     exc_info=True)

    logger.debug('Done bring down {}'.format(path))
    return json.dumps(_get_status(path))


@job('high', connection=redis_conn, timeout=600)
def destroy(path):
    logger.debug('Destroying {}'.format(path))

    vagrant = Vagrant(path)
    try:
        vagrant.destroy()
    except:
        logger.error('Failed to destroy machine {}'.format(path),
                     exc_info=True)

    logger.debug('Done destroying {}'.format(path))
    return json.dumps(_get_status(path))


@job('low', connection=redis_conn, timeout=60)
def status(path):
    os.putenv('HOME', '/root')
    logger.debug('Asking Status for {}'.format(path))
    try:
        status = _get_status(path)
    except:
        return json.dumps({'msg': 'error getting status'})

    logger.debug('Status : {} :: {}'.format(status, path))
    return json.dumps(status)


def _get_status(path):
    old_path = os.getcwd()
    try:
        os.chdir(path)
        statuses = str(sh.vagrant('status'))
    except:
        logger.error('Failed to get status of the machine {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)
    return statuses

if __name__ == '__main__':
    logger.debug('Env before fork : {}'.format(os.environ))
    # Tell rq what Redis connection to use
    with Connection():
        q = map(Queue, sys.argv[1:]) or [Queue()]
        Worker(q).work()
