# -=- encoding: utf-8 -=-
import sys
from config import VAGRANT_CONTROL_PATH
sys.path.append(VAGRANT_CONTROL_PATH)

from rq import Queue, Worker, Connection
from rq import get_current_job
from rq.decorators import job
from vagrant import Vagrant
from sh import git
import os
import logging
import sh
from sh import ErrorReturnCode
import re
import json
import time
from redis import Redis
redis_conn = Redis()

from vagrantControl.models.host import Host

basedir = os.path.abspath(os.path.dirname(__file__))
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('{}/vagrant-worker.log'.format(basedir))
# formatter = logging.Formatter('%(levelname) -10s %(asctime)s\
#    %(module)s:%(lineno)s %(funcName)s %(message)s')

# handler.setFormatter(formatter)
logger.addHandler(handler)
current_job = None


def resetEnv(host=None, environment=None):
    new_env = os.environ.copy()
    new_env['HOME'] = '/root'
    if host:
        new_env['VAGRANT_DEFAULT_PROVIDER'] = host.provider
    if environment:
        new_env['ENVIRONMENT'] = environment

    if host:
        for param in host.params.splitlines():
            if param != '' and '=' in param:
                key, value = param.split('=')
                new_env[key] = value.strip().replace("'", '').replace('"', '')

    return new_env


@job('low', connection=redis_conn, timeout=40)
def ip(path, machineName='default', host=None):
    logger.debug('Getting IP from vagrant machine {}'.format(machineName))
    new_env = resetEnv(host)
    ip = ''
    old_path = os.getcwd()
    os.chdir(path)

    try:
        machineType = sh.vagrant('status', machineName, _env=new_env)

        if 'stopped' not in machineType:
            if 'virtualbox' in machineType:
                ips = sh.vagrant('ssh', machineName, '-c', 'ip addr list eth1',
                                 _env=new_env)
                ips = str(ips)
                search = re.match(r'.* inet (.*)/24 brd',
                                  ips.stdout.replace('\n', ''))

                if search:
                    ip = search.group(1)
            elif 'lxc' in machineType or 'vsphere' in machineType:
                ips = sh.vagrant('ssh-config', machineName, _env=new_env)
                ips = str(ips)
                search = re.findall('HostName (.*)\n', ips, re.M)
                if search:
                    ip = search[0]
                # logger.debug(ip)

    except:
        logger.error('Unable to connect to machine to it\'s IP :: {}'
                     .format(path))

    os.chdir(old_path)
    return ip


@job('high', connection=redis_conn, timeout=600)
def run(path, environment, host, machineName):
    old_path = os.getcwd()
    new_env = resetEnv(host)

    current_job = get_current_job()
    _open_console(current_job.id)

    status = _get_status(path, host)
    if 'not created' not in status and host.provider not in status:
        try:
            os.chdir(path)
            for line in sh.vagrant('destroy', _iter=True, _ok_code=[0, 1, 2],
                                   _env=new_env):
                _log_console(current_job.id, str(line))
            os.chdir(old_path)

        except:
            logger.error('Failed to destroy machine {}'.format(path))

    try:
        os.chdir(path)

        for line in sh.vagrant('up', machineName, _iter=True, _env=new_env):
            _log_console(current_job.id, str(line))
        os.chdir(old_path)

    except ErrorReturnCode, e:
        for line in e.message.splitlines():
            logger.debug(line)
            _log_console(current_job.id, line)

    _close_console(current_job.id)

    return json.dumps(_get_status(path, host))


@job('high', connection=redis_conn, timeout=600)
def provision(path, environment, machineName, host):
    new_env = resetEnv(host, environment)
    # logger.debug('Running provision on {} with env {}'
    #            .format(path, environment))
    old_path = os.getcwd()
    current_job = get_current_job()
    try:
        os.chdir(path)
        _open_console(current_job.id)
        for line in sh.vagrant('provision', machineName, _iter=True,
                               _env=new_env):
            _log_console(current_job.id, str(line))
    except:
        logger.error('Failed to provision machine at {}'.format(path),
                     exc_info=True)
    _close_console(current_job.id)
    os.chdir(old_path)
    return json.dumps(_get_status(path, host))


@job('high', connection=redis_conn, timeout=600)
def clone(path, git_address, git_reference, host):
    new_env = resetEnv(host)
    logger.debug('Cloning {} with git_reference {} at {}'
                 .format(git_address, git_reference, path))
    old_path = os.getcwd()
    try:
        os.makedirs(path)
        os.chdir(path)

        git.clone(
            git_address,
            '.',
            '--recursive',
            '--branch',
            git_reference,
            '--depth',
            1,
            _env=new_env
        )
        logger.debug('{} {} {} {} {} {} {}'.format(
            git_address,
            '.',
            '--recursive',
            '--branch',
            git_reference,
            '--depth',
            1
        ))
    except:
        logger.error('Failed to clone project at {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)


@job('high', connection=redis_conn, timeout=600)
def stop(path, machineName, host=None):
    new_env = resetEnv(host)
    logger.debug('Bring down {}'.format(path))
    # logger.debug('Bring down {}'.format(path))
    old_path = os.getcwd()
    current_job = get_current_job()
    try:
        os.chdir(path)
        _open_console(current_job.id)
        for line in sh.vagrant('halt', machineName, _iter=True, _env=new_env):
            _log_console(current_job.id, str(line))
    except:
        logger.error('Failed to shut down machine {}'.format(path),
                     exc_info=True)

    _close_console(current_job.id)
    os.chdir(old_path)
    # logger.debug('Done bring down {}'.format(path))
    return json.dumps(_get_status(path, host))


@job('high', connection=redis_conn, timeout=600)
def destroy(path, host):
    # logger.debug('Destroying {}'.format(path))

    vagrant = Vagrant(path)
    try:
        vagrant.destroy()
    except:
        logger.error('Failed to destroy machine {}'.format(path),
                     exc_info=True)

    # logger.debug('Done destroying {}'.format(path))
    return json.dumps(_get_status(path, host))


@job('low', connection=redis_conn, timeout=60)
def status(path, host=None):
    try:
        status = _get_status(path, host)
    except:
        return json.dumps({'msg': 'error getting status'})

    # logger.debug('Status : {} :: {}'.format(status, path))
    return json.dumps(status)


@job('low', connection=redis_conn, timeout=60)
def get_git_references(git_address, project_id):
    resetEnv()
    os.chdir('/tmp')
    logger.debug('Getting git ref : git ls-remote {}'
                 .format(git_address))
    fullRefs = git('ls-remote', git_address)
    fullRefs = fullRefs.splitlines()

    ref = [refs.split('\t')[1].replace('refs/', '').replace('heads/', '')
           for refs in fullRefs]

    ref = [refs for refs in ref if refs != 'HEAD']

    return json.dumps(ref)


def _get_status(path, host):
    new_env = resetEnv(host)
    old_path = os.getcwd()
    statuses = None
    try:
        current_job = get_current_job()
        os.chdir(path)
        _open_console(current_job.id, private=True)
        for line in sh.vagrant('status', '--machine-readable',
                               _iter=True,
                               _env=new_env):
            _log_console(current_job.id, str(line), private=True)
        _close_console(current_job.id, private=True)

        statuses = _read_console(current_job.id, private=True)
    except:
        logger.error('Failed to get status of the machine {}'.format(path),
                     exc_info=True)

    os.chdir(old_path)
    return statuses


def _open_console(jobId, private=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)
    return redis_conn.set(job_key, '#BEGIN#\n')


def _read_console(jobId, private=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)
    return redis_conn.get(job_key)


def _log_console(jobId, line, private=False, test=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)

    console = redis_conn.get(job_key)
    if console is None:
        console = ''

    if test:
        logger.debug(line)
    redis_conn.set(job_key, console + line)
    expires = int(time.time()) + (5 * 60) + 10
    redis_conn.expireat(job_key, expires)


def _close_console(jobId, private=False):
    if private:
        job_key = '{}:console-private'.format(jobId)
    else:
        job_key = '{}:console'.format(jobId)
    console = redis_conn.get(job_key)
    if console is None:
        console = ''
    # logger.debug(console)
    return redis_conn.set(job_key, console + '\n#END#\n')


if __name__ == '__main__':
    # Tell rq what Redis connection to use
    with Connection():
        q = map(Queue, sys.argv[1:]) or [Queue()]
        Worker(q).work()
