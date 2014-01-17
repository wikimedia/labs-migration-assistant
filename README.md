## Welcome to Labs Migration Assistant!

This is a simple tool to help you determine whether all your Wikimedia Labs instances are ready
for the datacenter migration from pmtpa (Tampa) to eqiad (Ashburn). Currently there are four checks:
1. Check if you are running a self hosted puppet master
2. Check if your last puppet run is recent, less than 30 days old
3. Check if you are using shared project space ie /data/projects/
4. Check if you are using shared storage for $HOME

## Installation

``` shell
sudo python setup.py install
```

this will install all the dependencies and you should be good to go. 

## Run

The command to run the script is easy:

``` shell
cd labs-migration-assistant
fab migrate_ready --set wiki_username=YOUR_WIKI_USERNAME
# use your username for Wikitech
```

## Requirements

Development of this script was done using Python 2.7.5 on OSX 10.9. I expect that this would work fine
on Python 2.5 and 2.6 as well and I do not foresee problems with Linux either. But....bug reports are
always welcome and pull requests even more!

Use a recent version of pip.
## Contributing

1. Fork it
2. Create your feature branch (`git checkout -b my-new-feature`)
3. Commit your changes, including tests (`git commit -am 'Added some feature'`)
4. Push to the branch (`git push origin my-new-feature`)
5. Create new Pull Request, and mention @dvanliere.
