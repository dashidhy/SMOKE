import logging
from tqdm import tqdm

import torch

from smoke.utils import comm
from smoke.utils.timer import Timer, get_time_str
from smoke.data.datasets.evaluation import evaluate


def compute_on_dataset(model, data_loader, device, timer=None):
    model.eval()
    results_dict = {}
    cpu_device = torch.device("cpu")
    for batch in tqdm(data_loader):
        images, targets, image_ids = batch["images"], batch["targets"], batch["img_ids"]
        images = images.to(device)
        with torch.no_grad():
            if timer:
                timer.tic()
            output = model(images, targets)
            if timer:
                torch.cuda.synchronize()
                timer.toc()
            output = output.to(cpu_device)
        if targets[0].has_field("global_T_ego"):
            output = (output, torch.stack([t.get_field("ego_T_cam") for t in targets]).squeeze().to(cpu_device), torch.stack([t.get_field("global_T_ego") for t in targets]).squeeze().to(cpu_device))
        results_dict.update(
            {img_id: output for img_id in image_ids} # TODO: here seems image_ids actually only have size 1, code is not quite elegant
        )
    return results_dict


def inference(
        model,
        data_loader,
        dataset_name,
        eval_type="detection",
        device="cuda",
        output_folder=None,

):
    device = torch.device(device)
    num_devices = comm.get_world_size()
    logger = logging.getLogger(__name__)
    dataset = data_loader.dataset
    logger.info("Start evaluation on {} dataset({} images).".format(dataset_name, len(dataset)))

    total_timer = Timer()
    inference_timer = Timer()
    total_timer.tic()
    predictions = compute_on_dataset(model, data_loader, device, inference_timer)
    comm.synchronize()

    total_time = total_timer.toc()
    total_time_str = get_time_str(total_time)
    logger.info(
        "Total run time: {} ({} s / img per device, on {} devices)".format(
            total_time_str, total_time * num_devices / len(dataset), num_devices
        )
    )
    total_infer_time = get_time_str(inference_timer.total_time)
    logger.info(
        "Model inference time: {} ({} s / img per device, on {} devices)".format(
            total_infer_time,
            inference_timer.total_time * num_devices / len(dataset),
            num_devices,
        )
    )
    if not comm.is_main_process():
        return

    return evaluate(eval_type=eval_type,
                    dataset=dataset,
                    predictions=predictions,
                    output_folder=output_folder, )
