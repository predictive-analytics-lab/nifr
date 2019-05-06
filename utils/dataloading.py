import os
from pathlib import Path

import pandas as pd
import numpy as np
import torch

from torch.utils.data import TensorDataset, DataLoader

from ethicml.data.load import load_data
from ethicml.algorithms.utils import DataTuple
from sklearn.preprocessing import StandardScaler
from torchvision import transforms
from tqdm import tqdm

from data.cmnist import CMNIST
from data.colorized_mnist import ColorizedMNIST
from data.preprocess_cmnist import get_path_from_args, make_cmnist_dataset
from utils import utils


def load_adult_data(args):
    """Load dataset from the files specified in ARGS and return it as PyTorch datasets"""

    from ethicml.data import Adult
    from ethicml.preprocessing.train_test_split import train_test_split
    from ethicml.preprocessing.domain_adaptation import domain_split

    data = load_data(Adult())
    if args.add_sampling_bias:
        train_tuple, test_tuple = domain_split(
            datatup=data,
            tr_cond='education_Masters == 0. & education_Doctorate == 0.',
            te_cond='education_Masters == 1. | education_Doctorate == 1.'
        )
    else:
        train_tuple, test_tuple = train_test_split(data)

    # def load_dataframe(path: Path) -> pd.DataFrame:
    #     """Load dataframe from a parquet file"""
    #     with path.open('rb') as f:
    #         df = pd.read_feather(f)
    #     return torch.tensor(df.values, dtype=torch.float32)
    #
    # train_x = load_dataframe(Path(args.train_x))
    # train_s = load_dataframe(Path(args.train_s))
    # train_y = load_dataframe(Path(args.train_y))
    # test_x = load_dataframe(Path(args.test_x))
    # test_s = load_dataframe(Path(args.test_s))
    # test_y = load_dataframe(Path(args.test_y))

    # train_test_split()
    # train_data = TensorDataset(train_x, train_s, train_y)
    # test_data = TensorDataset(test_x, test_s, test_y)

    scaler = StandardScaler()

    train_scaled = pd.DataFrame(scaler.fit_transform(train_tuple.x), columns=train_tuple.x.columns)
    train_tuple = DataTuple(x=train_scaled, s=train_tuple.s, y=train_tuple.y)
    test_scaled = pd.DataFrame(scaler.transform(test_tuple.x), columns=test_tuple.x.columns)
    test_tuple = DataTuple(x=test_scaled, s=test_tuple.s, y=test_tuple.y)

    train_data = TensorDataset(*[torch.tensor(df.values, dtype=torch.float32) for df in train_tuple])
    test_data = TensorDataset(*[torch.tensor(df.values, dtype=torch.float32) for df in test_tuple])

    return train_data, test_data, train_tuple, test_tuple,


def get_mnist_data_tuple(args, data, train=True):
    dataset = "train" if train else "test"

    save_dir = Path(args.save)
    save_dir.mkdir(parents=True, exist_ok=True)
    LOGGER = utils.get_logger(logpath=save_dir / 'logs', filepath=Path(__file__).resolve())

    LOGGER.info("Making data tuple")

    data_path = get_path_from_args(args) / dataset

    if (os.path.exists(data_path / "x_values.npy") and os.path.exists(data_path / "s_values")
            and os.path.exists(data_path / "y_values")):
        LOGGER.info("data tuples found on file")
        x_all = np.load(data_path / "x_values.npy")
        s_all = pd.read_csv(data_path / "s_values", index_col=0)
        y_all = pd.read_csv(data_path / "y_values", index_col=0)
    else:
        LOGGER.info("data tuples haven't been created - this may take a while")
        data_loader = DataLoader(data, batch_size=args.batch_size)
        x_all, s_all, y_all = [], [], []

        for x, s, y in tqdm(data_loader):
            x_all.extend(x.numpy())
            s_all.extend(s.numpy())
            y_all.extend(y.numpy())

        x_all = np.array(x_all)
        np.save(data_path / 'x_values', x_all)
        # s_all = pd.DataFrame(np.array(s_all), columns=['sens_r', 'sens_g', 'sens_b'])
        s_all = pd.DataFrame(np.array(s_all), columns=['sens'])
        s_all.to_csv(data_path / "s_values")

        y_all = pd.DataFrame(np.array(y_all), columns=['label'])
        y_all.to_csv(data_path / "y_values")

    return DataTuple(x_all, s_all, y_all)


def load_cmnist_from_file(args):
    train_data = CMNIST(args, train=True)
    test_data = CMNIST(args, train=False, normalize_transform=train_data.normalize_transform)

    return train_data, test_data


def load_dataset(args):
    if args.dataset == 'cmnist':
        # make_cmnist_dataset(args)
        train_data = ColorizedMNIST(args.root, train=True,
                                    download=True, transform=transforms.ToTensor(),
                                    scale=args.scale,
                                    cspace=args.cspace,
                                    background=args.background,
                                    black=args.black)
        test_data = ColorizedMNIST(args.root, train=False,
                                   download=True, transform=transforms.ToTensor(),
                                   scale=args.scale,
                                   cspace=args.cspace,
                                   background=args.background,
                                   black=args.black)

        # train_data, test_data = load_cmnist_from_file(args)
        train_tuple, test_tuple = None, None
    else:
        train_data, test_data, train_tuple, test_tuple = load_adult_data(args)

    return train_data, test_data, train_tuple, test_tuple

# def save_date(args, root='../data'):
#     from torchvision.transforms import ToPILImage
#     path = Path(root) / args.dataset
#     dataloader = []
#     to_pil = ToPILImage()
#     for x, s, y in dataloader:
#         for sample in x.unfold(dim=0):
#             im = to_pil(x.detach().cpu())
#             im.save(path / , 'PNG')


def pytorch_data_to_dataframe(dataset):
    """Load a pytorch dataset into a DataTuple consisting of Pandas DataFrames"""
    # create data loader with one giant batch
    data_loader = DataLoader(dataset, batch_size=len(dataset), shuffle=False)
    # get the data
    data = next(iter(data_loader))
    # convert it to Pandas DataFrames
    data = [pd.DataFrame(tensor.numpy()) for tensor in data]
    # create a DataTuple
    return DataTuple(x=data[0], s=data[1], y=data[2])
