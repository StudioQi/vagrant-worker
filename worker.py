from daemon import Daemon
import os
import gearman
from vagrant import Vagrant


class App(Daemon):
    def run(self):
        while True:
            gm_worker = gearman.GearmanWorker(['localhost'])
            gm_worker.set_client_id('vagrant-worker-{}'.format(os.getpid()))
            gm_worker.register_task('start', run)
            gm_worker.register_task('stop', stop)
            gm_worker.register_task('status', status)
            gm_worker.work()


def run(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    print 'Bring up {}'.format(path)

    vagrant = Vagrant(path)
    vagrant.up()
    print 'Done'

    return _get_status(vagrant)


def stop(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    print 'Bring down {}'.format(path)

    vagrant = Vagrant(path)
    vagrant.halt()
    print 'Done'
    return _get_status(vagrant)


def status(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    print 'Status {}'.format(path)

    vagrant = Vagrant(path)
    return _get_status(vagrant)


def _get_path(gearman_job):
    return gearman_job.data


def _get_status(vagrant):
    statuses = vagrant.status()
    return ''.join([status + '::' + statuses[status] for status in statuses])


app = App('/tmp/test-{}.pid'.format(os.getpid()))
app.start()
