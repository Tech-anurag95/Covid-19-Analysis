import io
import os
import stat
import subprocess
import zipfile
from pathlib import Path
from shutil import rmtree
from time import sleep

import pandas as pd
import requests
import wbdata


def ensure_directory(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def _remove_readonly(func, path, _):
    """Allow deletion of read-only files on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def delete_directory(path):
    """
    Remove directory and retry on transient Windows file-lock errors.
    """
    path = Path(path)
    if not path.exists():
        return

    for attempt in range(5):
        try:
            rmtree(path, onerror=_remove_readonly)
            return
        except (FileNotFoundError, PermissionError, OSError):
            if attempt == 4:
                raise
            sleep(2)


def kill_stale_git_processes():
    """Stop previous git clone processes that can leave Windows file locks behind."""
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'git.exe' -and $_.CommandLine -match 'CSSEGISandData/COVID-19' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(['powershell', '-NoProfile', '-Command', command], check=False)


def download_covid():
    """
    Download COVID-19 case data from the archive endpoint to avoid Windows checkout failures.
    """

    archive_url = 'https://codeload.github.com/CSSEGISandData/COVID-19/zip/refs/heads/master'
    path = Path('./data/raw/COVID-19')
    archive_path = path.parent / 'COVID-19.zip'

    print('Downloading covid data.')

    kill_stale_git_processes()
    delete_directory(path=str(path))
    if archive_path.exists():
        archive_path.unlink()
    ensure_directory(path.parent)

    response = requests.get(url=archive_url, timeout=120)
    response.raise_for_status()
    archive_path.write_bytes(response.content)

    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(path.parent)

    extracted_dirs = sorted(
        candidate for candidate in path.parent.iterdir()
        if candidate.is_dir() and candidate.name.startswith('COVID-19')
    )
    if not extracted_dirs:
        raise FileNotFoundError('COVID-19 archive did not extract any expected folders.')

    extracted_dir = extracted_dirs[0]
    if extracted_dir != path:
        extracted_dir.rename(path)

    archive_path.unlink(missing_ok=True)


def download_countries():
    """
    Download country metadata with a stable fallback source.
    """

    url = 'https://raw.githubusercontent.com/datasets/country-codes/master/data/country-codes.csv'
    path = Path('./data/raw/datahub')

    print('Downloading country data.')

    delete_directory(path=str(path))
    ensure_directory(path)

    req = requests.get(url=url, timeout=60)
    req.raise_for_status()

    df = pd.read_csv(io.StringIO(req.text))
    continent_codes = {
        'Africa': 'AF',
        'Asia': 'AS',
        'Europe': 'EU',
        'North America': 'NA',
        'Oceania': 'OC',
        'South America': 'SA',
        'Antarctica': 'AN',
    }

    output = df.loc[:, ['Continent', 'official_name_en', 'ISO3166-1-Alpha-2', 'ISO3166-1-Alpha-3', 'ISO3166-1-numeric']].copy()
    output.columns = ['Continent_Name', 'Country_Name', 'Two_Letter_Country_Code', 'Three_Letter_Country_Code', 'Country_Number']
    output['Continent_Code'] = output['Continent_Name'].map(continent_codes)
    output = output[['Continent_Code', 'Continent_Name', 'Two_Letter_Country_Code', 'Three_Letter_Country_Code', 'Country_Number', 'Country_Name']]
    output.to_csv(path / 'countries.csv', index=False)


def download_world_bank():
    """
    Download data from the World Bank
    """

    path = Path('./data/raw/world_bank')

    delete_directory(path=str(path))
    ensure_directory(path)

    indicators = [{'NY.GDP.PCAP.PP.CD': 'GDP per capita, PPP (current international $)'},
                  {'SP.POP.TOTL': 'Population, total'},
                  {'SP.URB.TOTL.IN.ZS': 'Urban population (% of total population)'},
                  {'EN.POP.SLUM.UR.ZS': 'Urban population (% of total population)'},
                  {'SP.RUR.TOTL.ZS': 'Urban population (% of total population)'},
                  {'SP.DYN.LE00.IN': 'Life expectancy at birth, total (years)'},
                  {'SH.XPD.CHEX.GD.ZS': 'Current health expenditure (% of GDP)'}]

    for indicator in indicators:
        file_name = list(indicator.keys())[0]
        full_path = path / f'{file_name}.csv'

        print(f'Downloading {indicator}.')

        try:
            df = wbdata.get_dataframe(indicator)
            df.to_csv(full_path)
            sleep(2)
        except Exception:
            print(f'Download failed for {indicator}')


if __name__ == '__main__':
    download_covid()
    download_countries()
    download_world_bank()