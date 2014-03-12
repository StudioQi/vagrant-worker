# vagrant-worker

A small gearman daemon that can be run in parallel to start, stop, provision and destroy vagrant machines.
Currently support LXC and VirtualBox as provider. Don't forget to install the [vagrant-lxc](https://github.com/fgrehm/vagrant-lxc) plugin if you need LXC support.

This project is used by [vagrant-control](https://github.com/Pheromone/vagrant-control) to spawn the machines.

Keep in mind that this project will be completely rewritten when possible to move to python-rq instead of Gearman and a proper handling of daemon. 

# Note 

Keep in mind that this project is closer to ALPHA than to STABLE. DO NOT use on production system.
