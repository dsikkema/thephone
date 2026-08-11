#!/usr/bin/env bash
if [[ $(pwd) != '/Users/dale/home/work/dalephone/phoneapp' ]]; then
  exit 1
fi

if [[ $1 != '-f' ]]; then
  rsync -anv --delete --exclude-from=.gitignore . dale@cyberology:phone
  echo -n "Proceed? (y/n) "
  read -n 1 proceed
  echo
else
  proceed='y'
fi


if [[ $proceed = 'y' ]]; then
  echo 'Sending'
  rsync -av --delete --exclude-from=.gitignore . dale@cyberology:phone
else
  echo 'Aborting'
fi
