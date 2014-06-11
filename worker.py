# -=- encoding: utf-8 -=-
from rq import Queue, Worker, Connection
from rq import get_current_job
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
# formatter = logging.Formatter('%(levelname) -10s %(asctime)s\
#    %(module)s:%(lineno)s %(funcName)s %(message)s')

# handler.setFormatter(formatter)
logger.addHandler(handler)
current_job = None


def resetEnv():
    os.putenv('HOME', '/root')
    os.putenv('VAGRANT_DEFAULT_PROVIDER', 'lxc')


@job('low', connection=redis_conn, timeout=40)
def ip(path):
    logger.debug('Getting IP from vagrant machine')
    ip = ''
    old_path = os.getcwd()
    os.chdir(path)

    try:
        machineType = sh.vagrant('status')

        if 'stopped' not in machineType:
            if 'virtualbox' in machineType:
                ips = sh.vagrant('ssh', '-c', 'ip addr list eth1')
                ips = str(ips)
                search = re.match(r'.* inet (.*)/24 brd',
                                  ips.stdout.replace('\n', ''))

                if search:
                    ip = search.group(1)
            elif 'lxc' in machineType or 'vsphere' in machineType:
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
    resetEnv()

    logger.debug('Bring up {} with eth {} and\
 environment set to {} with provider {}'
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
    resetEnv()
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
    resetEnv()
    logger.debug('Asking Status for {}'.format(path))
    try:
        status = _get_status(path)
    except:
        return json.dumps({'msg': 'error getting status'})

    logger.debug('Status : {} :: {}'.format(status, path))
    return json.dumps(status)


def _get_status(path):
    old_path = os.getcwd()
    statuses = None
    try:
        current_job = get_current_job()
        os.chdir(path)
        logger.debug('-'*20)
        # statuses = str(sh.vagrant('status', _out=_log_console, _tee=True))
        _open_console(current_job.id)
        for line in sh.vagrant('status', _iter=True):
            _log_console(current_job.id, str(line))
        _close_console(current_job.id)

        statuses = _read_console(current_job.id)
        logger.debug(statuses)
    except:
        logger.error('Failed to get status of the machine {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)
    return statuses


def _open_console(jobId):
    job_key = '{}:console'.format(jobId)
    return redis_conn.set(job_key, '#BEGIN#\n')


def _read_console(jobId):
    job_key = '{}:console'.format(jobId)
    return redis_conn.get(job_key)


def _log_console(jobId, line):
    job_key = '{}:console'.format(jobId)
    console = redis_conn.get(job_key)
    if console is None:
        console = ''
    redis_conn.set(job_key, console + line)


def _close_console(jobId):
    job_key = '{}:console'.format(jobId)
    console = redis_conn.get(job_key)
    if console is None:
        console = ''
    logger.debug(console)
    return redis_conn.set(job_key, console + '\n#END#\n')


if __name__ == '__main__':
    logger.debug('Env before fork : {}'.format(os.environ))
    # Tell rq what Redis connection to use
    with Connection():
        q = map(Queue, sys.argv[1:]) or [Queue()]
        Worker(q).work()
